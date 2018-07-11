import os

import keras
import numpy as np
import pandas as pd
import pytest

import bluenot
import generators.luke
import models.luke


def test_to_arrays():
    x_dict = {
        'a': np.array([1]),
        'b': np.array([2]),
        'c': np.array([3]),
    }
    y_series = pd.Series(
        data=np.array([1, 2, 3]),
        index=['a', 'b', 'c'],
    )

    x_arr, y_arr = bluenot.to_arrays(x_dict, y_series)
    print(y_arr)
    assert np.all(x_arr == np.expand_dims(y_arr, axis=1))


@pytest.mark.skipif(os.uname().nodename != 'gpu1708',
                    reason='Test takes a long time without a GPU')
def test_start_job_no_err():
    x_train = np.random.uniform(0, 255, (100, 220, 220, 3))
    y_train = np.random.uniform(0, 255, (100, 5))
    x_valid = np.random.uniform(0, 255, (20, 220, 220, 3))
    y_valid = np.random.uniform(0, 255, (20, 5))
    name = 'test_job'
    params = {
        'data': {
            # A directory containing a list of numpy files with
            # patient ID as their filename
            'data_dir': '/home/lzhu7/elvo-analysis/data/'
                        'processed-standard/arrays/',
            # A CSV file generated by saving a pandas DataFrame
            'labels_path': '/home/lzhu7/elvo-analysis/data/'
                           'processed-standard/labels.csv',
            'index_col': 'Anon ID',
            'label_col': 'Location of occlusions on CTA (Matt verified)',
        },

        'val_split': 0.2,

        'generator': generators.luke.standard_generators,

        'model': {
            # The callable must take in **kwargs as an argument
            'model_callable': models.luke.inception_resnet,
            'dropout_rate1': 0.8,
            'dropout_rate2': 0.7,
            'batch_size': 8,
            'rotation_range': 20,  # , 30],
            'optimizer': keras.optimizers.Adam(lr=1e-4),
            'loss': keras.losses.categorical_crossentropy,
        },
    }
    bluenot.start_job(x_train, y_train, x_valid, y_valid,
                      name=name,
                      params=params, redirect=False,
                      epochs=0)


@pytest.mark.skipif(os.uname().nodename != 'gpu1708',
                    reason='Test uses data only on gpu1708')
def test_prepare_data_correct_dims():
    params = {
        'data': {
            # A directory containing a list of numpy files with
            # patient ID as their filename
            'data_dir': '/home/lzhu7/elvo-analysis/data/'
                        'processed-standard/arrays/',
            # A CSV file generated by saving a pandas DataFrame
            'labels_path': '/home/lzhu7/elvo-analysis/data/'
                           'processed-standard/labels.csv',
            'index_col': 'Anon ID',
            'label_col': 'occlusion_exists',
        },

        'seed': 0,
        'val_split': 0.2,

        'generator': generators.luke.standard_generators,

        'model': {
            # The callable must take in **kwargs as an argument
            'model_callable': models.luke.inception_resnet,
            'dropout_rate1': 0.8,
            'dropout_rate2': 0.7,
            'batch_size': 8,
            'rotation_range': 20,  # , 30],
            'optimizer': keras.optimizers.Adam(lr=1e-4),
            'loss': keras.losses.binary_crossentropy,
        },
    }
    _, _, y_train, y_test = bluenot.prepare_data(params)
    assert y_train.ndim == 2
    assert y_test.ndim == 2


@pytest.mark.skipif(os.uname().nodename != 'gpu1708',
                    reason='Test uses data only on gpu1708')
def test_prepare_and_job():
    params = {
        'data': {
            # A directory containing a list of numpy files with
            # patient ID as their filename
            'data_dir': '/home/lzhu7/elvo-analysis/data/'
                        'processed-standard/arrays/',
            # A CSV file generated by saving a pandas DataFrame
            'labels_path': '/home/lzhu7/elvo-analysis/data/'
                           'processed-standard/labels.csv',
            'index_col': 'Anon ID',
            'label_col': 'Location of occlusions on CTA (Matt verified)',
        },

        'val_split': 0.2,
        'seed': 0,

        'generator': generators.luke.standard_generators,

        'model': {
            # The callable must take in **kwargs as an argument
            'model_callable': models.luke.resnet,
            'dropout_rate1': 0.8,
            'dropout_rate2': 0.7,
            'batch_size': 8,
            'rotation_range': 20,  # , 30],
            'optimizer': keras.optimizers.Adam(lr=1e-4),
            'loss': keras.losses.categorical_crossentropy,
        },
    }
    x_train, x_valid, y_train, y_valid = bluenot.prepare_data(params)
    bluenot.start_job(x_train,
                      y_train,
                      x_valid,
                      y_valid,
                      name='test_prepare_and_job',
                      params=params)
