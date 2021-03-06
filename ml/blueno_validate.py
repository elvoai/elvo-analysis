"""
Script to automate validating an ML pipeline specified by ParamConfig.

Evaluation is done by retraining the given model, and evaluating the
trained model on the test set. One can evaluate the model multiple
times; the resulting metrics will then be the average of the
several iterations. Shuffling seeds are randomized every time.

There are two methods to use this script:
- kibana: A list of ParamConfig will automatically be generated based
    on the address to access the database, and the lower and upper
    thresholds of best_val_acc. This list of ParamConfig will then
    be automatically evaluated.
- param-list-config: You will specify a list of ParamConfig manually,
    through a config file. The script will look for EVAL_PARAM_LIST,
    and evaluate all ParamConfig there.

Currently the script will upload text results to Slack only.
Graphs are not uploaded since they will probably not provide
valuable information in evaluation, although this is subject to change.

TODO:
- Support multithreading (similar to bluenot.py)
- Possibly upload results to Kibana
"""

import os
import sys
import logging
import argparse
import importlib
import pathlib
import datetime
import random
import multiprocessing
import time

import numpy as np
import keras
import keras.metrics as metrics
from keras.callbacks import ModelCheckpoint
from keras.models import load_model
import sklearn.metrics

from blueno.elasticsearch import search_top_models, filter_top_models
from blueno import (
    types, preprocessing, utils,
    elasticsearch, logger, slack
)
from models.luke import resnet
from generators.luke import standard_generators


def get_models_to_train(address, lower, upper, data_dir):
    """
    Fetches relevant configurations to train from Kibana,
    based on the upper and lower bounds of best_val_acc
    specified.

    :param address: Address to connect to Kibana
    :param lower: Lower bound of best_val_acc
    :param upper: Upper bound of best_val_acc
    :param data_dir: Local directory to specify where the datasets are.
        This is required for specifying 'data_dir' in DataConfig.

    :return: A list of configs to train.
    """
    docs = search_top_models(address, lower=lower, upper=upper)
    docs = filter_top_models(address, docs)
    docs_to_train = []
    for doc in docs:
        data = {}
        data['purported_accuracy'] = doc.best_val_acc
        data['purported_loss'] = doc.best_val_loss
        data['purported_sensitivity'] = doc.best_val_sensitivity
        data['date'] = doc.created_at
        data['job_name'] = doc.job_name
        if hasattr(doc, 'author'):
            data['author'] = doc.author
        else:
            data['author'] = 'None'

        # Dataset information
        if 'gcs_url' in doc:
            gcs_url = doc.gcs_url
        else:
            folder = doc.data_dir.split('/')[-2]
            # data_dir naming structure is super inconsistent.
            # Here are some edge cases to cover weird names.
            if folder == 'processed':
                folder = 'processed-sumera-1'

            # If not preprocessed (using numpy_compressed), skip
            if folder == 'numpy':
                continue

            gcs_url = 'gs://elvos/processed/{}'.format(folder)

        folder = os.path.join(data_dir, gcs_url.split('/')[-1])
        data['local_dir'] = folder
        data_info = {
            'data_dir': os.path.join(folder,
                                     'arrays/'),
            'labels_path': os.path.join(folder,
                                        'labels.csv'),
            'index_col': 'Anon ID',
            'label_col': 'occlusion_exists',
            'gcs_url': gcs_url
        }

        # Model information
        model = {
            'dropout_rate1': doc.dropout_rate1,
            'dropout_rate2': doc.dropout_rate2,
            'optimizer': 'Adam',
            'loss': keras.losses.binary_crossentropy,
            'freeze': False,
            'model_callable': resnet,
        }

        # Generator / Image transformation information
        generator = {}
        generator_params = ['rotation_range', 'width_shift_range',
                            'height_shift_range', 'shear_range',
                            'zoom_range', 'horizontal_flip',
                            'vertical_flip']
        default_params = [30, 0.1, 0.1, 0, 0.1, True, False]
        for param, default_value in zip(generator_params, default_params):
            if param in doc:
                generator[param] = doc[param]
            else:
                generator[param] = default_value
        # Edge case for zooms
        if (isinstance(generator['zoom_range'], str) and
           generator['zoom_range'][0] == '('):
            generator['zoom_range'] = generator['zoom_range'][1:-1].split(',')

        generator['generator_callable'] = standard_generators

        params = {
            'data': types.DataConfig(**data_info),
            'model': types.ModelConfig(**model),
            'generator': types.GeneratorConfig(**generator),
            'batch_size': doc.batch_size,
            'seed': 999,
            'val_split': 0.1,
            'max_epochs': 100,
            'early_stopping': True,
            'reduce_lr': False,
            'job_fn': None,
            'job_name': None
        }

        data['params'] = types.ParamConfig(**params)
        docs_to_train.append(data)
    return docs_to_train


def __get_data_if_not_exists(gcs_dir, local_dir):
    """
    Downloads the data from GCS if the folder from local_dir
    does not exist.

    :params gcs_dir: The GCS directory to download from, e.g.
        gs://elvos/numpy
    :params local_dir: The local directory where the dataset should exist.

    :return: True if the dataset exists or the downloa was successful.
        False if the dataset failed to download (in which case you
        should skip configs that use this dataset, because the
        dataset probably does not exist.)
    """
    if not os.path.isdir(local_dir):
        logging.info(('Dataset {} does not exist. '
                      'Downloading from GCS...'.format(local_dir)))
        os.mkdir(local_dir)
        exit = os.system(
            'gsutil -m rsync -r -d {} {}'.format(gcs_dir, local_dir))
        if exit != 0:
            os.rmdir(local_dir)
        return exit == 0
    return True


def __load_data(params):
    """
    Loads the data.

    :params params: The ParamConfig file in question
    :return: train_data, validation_data, test_data,
        train_labels, vaidation_labels, test_labels,
        train_ids, validation_ids, test_ids
    """
    return preprocessing.prepare_data(params)


def __train_model(params, x_train, y_train, x_valid, y_valid,
                  no_early_stopping=False, data_dir='../tmp/'):
    """
    Trains the model.

    :params params: The ParamConfig in question
    :params x_train: The training data
    :params y_train: The training labels
    :params x_valid: The validation data
    :params y_valid: The validation labels
    :params no_early_stopping: Determine whether to use no early stopping
    :params data_dir: Temp directory

    :return: The trained model, and the training history.
    """
    train_gen, valid_gen = params.generator.generator_callable(
        x_train, y_train,
        x_valid, y_valid,
        params.batch_size,
        **params.generator.__dict__
    )

    model = params.model.model_callable(input_shape=x_train.shape[1:],
                                        num_classes=y_train.shape[1],
                                        **params.model.__dict__)
    model_metrics = ['acc',
                     utils.sensitivity,
                     utils.specificity,
                     utils.true_positives,
                     utils.false_negatives]
    model.compile(
        optimizer=getattr(keras.optimizers, params.model.optimizer)(lr=1e-5),
        loss=params.model.loss,
        metrics=model_metrics)

    if no_early_stopping:
        model_filename = str(datetime.datetime.now())
        model_filepath = '{}/{}.hdf5'.format(data_dir, model_filename)
        cbs = utils.create_callbacks(x_train, y_train, x_valid, y_valid,
                                     early_stopping=False,
                                     reduce_lr=params.reduce_lr)
        cbs.append(ModelCheckpoint(filepath=model_filepath,
                                   save_best_only=True,
                                   monitor='val_acc',
                                   mode='max',
                                   verbose=1))
    else:
        cbs = utils.create_callbacks(x_train, y_train, x_valid, y_valid,
                                     early_stopping=params.early_stopping,
                                     reduce_lr=params.reduce_lr)

    history = model.fit_generator(train_gen,
                                  epochs=params.max_epochs,
                                  validation_data=valid_gen,
                                  verbose=2,
                                  callbacks=cbs)

    if no_early_stopping:
        metrics.sensitivity = utils.sensitivity
        metrics.specificity = utils.specificity
        metrics.true_positives = utils.true_positives
        metrics.false_negatives = utils.false_negatives
        model = load_model(model_filepath)
        os.remove(model_filepath)
    return model, history


def evaluate_model(x_test, y_test, model, params,
                   normalize=True, x_train=None):
    """
    Evaluates the model.

    :params x_test: The test data
    :params y_test: The test labels
    :params model: The model to evaluate
    :params params: The ParamConfig to use
    :params normalize: Whether to normalize the test data based on
        training data
    :params x_train: The training data (used to normalize test data)
    :return: Evaluation results (list of metrics)
    """
    if normalize:
        if x_train is None:
            raise ValueError(('Must specify training data if normalize '
                              'is set to True.'))
        else:
            x_mean = np.array([x_train[:, :, :, 0].mean(),
                               x_train[:, :, :, 1].mean(),
                               x_train[:, :, :, 2].mean()])
            x_std = np.array([x_train[:, :, :, 0].std(),
                              x_train[:, :, :, 1].std(),
                              x_train[:, :, :, 2].std()])
            x_test = (x_test - x_mean) / x_std

    metrics = ['acc',
               utils.sensitivity,
               utils.specificity,
               utils.true_positives,
               utils.false_negatives]
    model.compile(optimizer=params.model.optimizer,
                  loss=params.model.loss,
                  metrics=metrics)

    results = model.evaluate(x=x_test, y=y_test, batch_size=1,
                             verbose=1)

    y_pred = model.predict(x_test, batch_size=1, verbose=1)
    auc_score = sklearn.metrics.roc_auc_score(y_test, y_pred)
    results.append(auc_score)
    return results


def iterate_eval(num_iterations, params, gpu,
                 job_name='None',
                 job_date=str(datetime.datetime.now()), author='None',
                 purported_loss='None', purported_accuracy='None',
                 purported_sensitivity='None',
                 slack_token=None,
                 no_early_stopping=False,
                 log_dir='../logs/', data_dir='../tmp/',
                 address=None):
    """
    Creates logs, and trains the model for a number of iterations.

    :params num_iterations: Number of iterations to run the model
    :params params: The ParamConfig to use
    :params gpu: The GPU number to use
    :params job_name: The job name
    :params job_date: The job date
    :params author: The author
    :params purported_loss: The purported loss (from validation)
    :params purported_acc: The purported accuracy (from validation)
    :prams purported_sensitivity: The purported sensitivity (from validation)
    :params slack_token: The slack token, to upload to Slack
    :params no_early_stopping: Determine whether to use early stopping
    :params log_dir: The directory to store logs
    :params data_dir: Temporary directory to store random files
    :params address: Address to upload to Kibana
    :returns:
    """
    os.environ['CUDA_VISIBLE_DEVICES'] = gpu

    # Configure the job to log all output to a specific file
    log_filepath = None
    filename = str(datetime.datetime.now())
    if log_dir:
        if '/' in job_name:
            raise ValueError("Job name cannot contain '/' character")
        log_filepath = str(pathlib.Path(log_dir) / '{}.log'.format(filename))
        assert log_filepath.startswith(log_dir)
        logger.configure_job_logger(log_filepath, level=logging.INFO)

    logging.info("----------------Evaluation-------------------")
    logging.info(params)
    logging.info('Job name: {}'.format(job_name))
    logging.info('Author: {}'.format(author))
    logging.info('Job date: {}'.format(job_date))
    logging.info('Purported accuracy: {}'.format(purported_accuracy))
    logging.info('Purported loss: {}'.format(purported_loss))
    logging.info('Purported sensitivity: {}'.format(purported_sensitivity))

    result_list = []
    for i in range(int(num_iterations)):
        logging.info("-----Iteration {}-----".format(i + 1))
        params.seed = random.randint(0, 1000000)
        logging.info("Seed: {}".format(params.seed))
        (x_train, x_valid, x_test, y_train, y_valid, y_test,
         _, _, _) = __load_data(params)
        model, history = __train_model(params, x_train, y_train,
                                       x_valid, y_valid,
                                       no_early_stopping=no_early_stopping,
                                       data_dir=data_dir)
        result = evaluate_model(x_test, y_test, model, params,
                                normalize=True, x_train=x_train)
        result_list.append(result)
        logging.info("-----Results {}-----".format(i + 1))
        logging.info("Seed: {}".format(params.seed))
        logging.info('Loss: {}'.format(result[0]))
        logging.info('Acc: {}'.format(result[1]))
        logging.info('Sensitivity: {}'.format(result[2]))
        logging.info('Specificity: {}'.format(result[3]))
        logging.info('True Positives: {}'.format(result[4]))
        logging.info('False Negatives: {}'.format(result[5]))
        logging.info('AUC: {}'.format(result[6]))

        val_loss_list = [s for s in history.history.keys() if
                         'loss' in s and 'val' in s]
        val_acc_list = [s for s in history.history.keys() if
                        'acc' in s and 'val' in s]
        for l in val_loss_list:
            logging.info('End val loss: {}'.format(history.history[l][-1]))
            logging.info('Max val loss: {}'.format(max(history.history[l])))
        for l in val_acc_list:
            logging.info('End val acc: {}'.format(history.history[l][-1]))
            logging.info('Max val loss: {}'.format(max(history.history[l])))

        if slack_token is not None:
            slack.write_iteration_results(
                params, result, slack_token, job_name=job_name,
                job_date=job_date, purported_accuracy=purported_accuracy,
                purported_loss=purported_loss,
                purported_sensitivity=purported_sensitivity, i=i)

    average_list = np.average(result_list, axis=0)
    logging.info("-----Final Results-----")
    logging.info('Loss: {}'.format(average_list[0]))
    logging.info('Acc: {}'.format(average_list[1]))
    logging.info('Sensitivity: {}'.format(average_list[2]))
    logging.info('Specificity: {}'.format(average_list[3]))
    logging.info('True Positives: {}'.format(average_list[4]))
    logging.info('False Negatives: {}'.format(average_list[5]))
    logging.info('AUC: {}'.format(average_list[6]))

    if slack_token is not None:
        slack.write_iteration_results(
            params, average_list, slack_token, job_name=job_name,
            job_date=job_date, purported_accuracy=purported_accuracy,
            purported_loss=purported_loss,
            purported_sensitivity=purported_sensitivity, final=True)

    # Upload to Kibana
    if log_dir:
        val_index = elasticsearch.create_new_connection(
            address, index='validation_jobs')
        val_job = elasticsearch.get_validation_job_from_log(log_filepath)
        elasticsearch.insert_or_ignore(val_job, index=val_index)


def multiprocess(models, num_iterations, gpus, slack_token=None,
                 no_early_stopping=False, address=None,
                 log_dir='../logs/', data_dir='../tmp/'):
    """
    Separate training to multiple processes.

    :params models: The param list to use
    :params num_iterations: Number of iterations to train each model
    :params gpus: The list of GPUS to use; a list of number strings
    :params slack_token: Slack token to use, to upload to Slack
    :params no_early_stopping: Determine whether to use early stopping
    :params address: Address to upload log to Kibana
    :params log_dir: Directory to store logs
    :params data_dir: Temporary directory to store random files
    :returns:
    """
    gpu_index = 0
    processes = []
    print(gpus)

    for model in models:
        params = model['params']
        data_loaded = __get_data_if_not_exists(params.data.gcs_url,
                                               model['local_dir'])
        if not data_loaded:
            logging.info('This directory does not exist. Moving on...')
        else:
            p = multiprocessing.Process(
                target=iterate_eval,
                args=(num_iterations, params, gpus[gpu_index]),
                kwargs={
                    'job_name': model['job_name'],
                    'job_date': model['date'],
                    'author': model['author'],
                    'purported_accuracy': model['purported_accuracy'],
                    'purported_loss': model['purported_loss'],
                    'purported_sensitivity': model['purported_sensitivity'],
                    'slack_token': slack_token,
                    'no_early_stopping': no_early_stopping,
                    'address': address,
                    'log_dir': log_dir,
                    'data_dir': data_dir
                })
            logging.info('Running at GPU {}'.format(gpus[gpu_index]))
            gpu_index += 1
            gpu_index %= len(gpus)

            p.start()
            processes.append(p)

            if gpu_index == 0:
                logging.info('All gpus used, calling join on processes...')
                for p in processes:
                    p.join()
                processes = []
            time.sleep(60)


def parse_args(args):
    """
    Parse arguments for this script.
    """
    parser = argparse.ArgumentParser(description='Evaluation script.')
    subparsers = parser.add_subparsers(
        help='Arguments for specific evaluation types.',
        dest='eval_type'
    )
    subparsers.required = True

    param_parser = subparsers.add_parser('param-list')
    param_parser.add_argument(
        'param-list-config',
        help=('Path to config file. This file must have a list of '
              'ParamConfig objects stored in EVAL_PARAM_LIST.')
    )

    kibana_parser = subparsers.add_parser('kibana')
    kibana_parser.add_argument('--address',
                               help='Address to access Kibana.',
                               default='http://104.196.51.205')
    kibana_parser.add_argument('--lower',
                               help='Lower bound of best_val_acc to search.',
                               default='0.85')
    kibana_parser.add_argument('--upper',
                               help='Upper bound of best_val_acc to search.',
                               default='0.93')

    parser.add_argument(
        '--gpu',
        help=('Ids of the GPU to use (as reported by nvidia-smi). '
              'Separated by comma, no spaces. e.g. 0,1'),
        default=None
    )
    parser.add_argument(
        '--log-dir',
        help=('Location to store logs.'),
        default='../logs/'
    )

    parser.add_argument(
        '--data-dir',
        help=('Location to store temporary files.'),
        default='../tmp/'
    )

    parser.add_argument(
        '--config',
        help=('Configuration file, if you want to specify GPU and '
              'log directories there.'),
        default=None
    )
    parser.add_argument(
        '--num-iterations',
        help=('Number of times to test a parameter config. '
              'Evaluation results are averaged.'),
        default=1
    )
    parser.add_argument(
        '--slack-token',
        help=('Slack token, to upload results to slack.'),
        default=None
    )

    parser.add_argument(
        '--no-early-stopping',
        help=('Saves best model after running max epochs, '
              'instead of early stopping'),
        action='store_true'
    )

    return parser.parse_args(args)


def check_user_config(config):
    """
    Check param-list-config to see if it is valid.
    """
    logging.info('Checking that user config has all required attributes')
    logging.info('LOG_DIR: {}'.format(config.LOG_DIR))
    logging.info('DATA_DIR: {}'.format(config.DATA_DIR))
    logging.info('gpus: {}'.format(config.gpus))
    logging.info('num_iterations: {}'.format(config.num_iterations))
    logging.info('SLACK_TOKEN: {}'.format(config.SLACK_TOKEN))
    logging.info('no_early_stopping: {}'.format(config.no_early_stopping))
    for attr in ['LOG_DIR', 'DATA_DIR', 'gpus', 'num_iterations',
                 'SLACK_TOKEN', 'no_early_stopping']:
        if not hasattr(config, attr):
            raise AttributeError('User config file is missing {}'.format(attr))


def check_config(config):
    """
    Check param-list-config to see if it is valid.
    """
    logging.info('Checking that config has all required attributes')
    logging.info('EVAL_PARAM_LIST: {}'.format(config.EVAL_PARAM_LIST))
    if (not (isinstance(config.EVAL_PARAM_LIST, list)) or
       not (isinstance(config.EVAL_PARAM_LIST[0], types.ParamConfig))):
        raise ValueError('EVAL_PARAM_LIST must be a list of ParamConfig')


def main(args=None):
    # Parse arguments
    if args is None:
        args = sys.argv[1:]
    args = parse_args(args)

    # Set config if exists
    if args.config is not None:
        user_config = importlib.import_module(args.config)
        check_user_config(user_config)
        args.log_dir = user_config.LOG_DIR
        args.data_dir = user_config.DATA_DIR
        args.gpu = user_config.gpus
        args.num_iterations = user_config.num_iterations
        args.slack_token = user_config.SLACK_TOKEN
        args.no_early_stopping = user_config.no_early_stopping

    # Set logger
    parent_log_file = pathlib.Path(
        args.log_dir) / 'eval-results-{}.txt'.format(
        datetime.datetime.utcnow().isoformat()
    )
    logger.configure_parent_logger(parent_log_file, level=logging.INFO)

    # Choose GPU to use
    if args.gpu:
        os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
        gpus = args.gpu.split(',')
    else:
        gpus = ['0']

    # Set configurations
    num_iterations = args.num_iterations
    slack_token = args.slack_token
    no_early_stopping = args.no_early_stopping

    if args.eval_type == 'kibana':
        # Fetch params list from Kibana to evaluate
        models = get_models_to_train(args.address, args.lower,
                                     args.upper, args.data_dir)
        multiprocess(models, num_iterations, gpus, slack_token=slack_token,
                     no_early_stopping=no_early_stopping,
                     address=args.address, log_dir=args.log_dir,
                     data_dir=args.data_dir)

    else:
        # Manual evaluation of a list of ParamConfig
        logging.info('Using config {}'.format(args.param_list_config))
        param_list_config = importlib.import_module(args.param_list_config)
        check_config(param_list_config)

        params = param_list_config.EVAL_PARAM_LIST
        multiprocess(params, num_iterations, gpus, slack_token=slack_token,
                     no_early_stopping=no_early_stopping,
                     address=args.address, log_dir=args.log_dir,
                     data_dir=args.data_dir)


if __name__ == '__main__':
    main()
