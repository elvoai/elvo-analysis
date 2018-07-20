import logging

import numpy as np
import pandas as pd

from lib import cloud_management as cloud  # , roi_transforms, transforms


def configure_logger():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def clean_data():
    configure_logger()
    client = cloud.authenticate()
    bucket = client.get_bucket('elvos')

    # iterate through every source directory...
    prefix = "chunk_data/normal/positive_no_aug"
    logging.info(f"cleaning: deleting positive chunks from {prefix}")

    for in_blob in bucket.list_blobs(prefix=prefix):
        in_blob.delete()


def create_chunks(annotations_df: pd.DataFrame):
    client = cloud.authenticate()
    bucket = client.get_bucket('elvos')

    # loop through every positive array on GCS
    # no need to loop through negatives, as those are fine in their
    # current state
    for in_blob in bucket.list_blobs(prefix='chunk_data/normal/positive'):

        # get the file id
        file_id = in_blob.name.split('/')[3]
        file_id = file_id.split('.')[0]

        logging.info(f'getting {file_id}')
        # copy region if it's the original image, not a rotation/
        # reflection

        if file_id.endswith('_1'):
            arr = cloud.download_array(in_blob)
            logging.info(f'downloading {file_id}')
            cloud.save_chunks_to_cloud(arr, 'normal',
                                       'positive_no_aug',
                                        file_id)


def create_labels(annotations_df: pd.DataFrame):
    client = cloud.authenticate()
    bucket = client.get_bucket('elvos')

    print("HELLO AGAIN")
    labels_df = pd.read_csv('/home/amy/data/augmented' \
                            '_annotated_labels1.csv')
    print(len(labels_df))

    for index, row in labels_df.iterrows():
        print(str(row[0]) + ": " + row[1])
        if row[2] == 1 and not row[1].endswith('_1'):
            labels_df = labels_df.drop(row[0])
            print("Dropping patient " + str(row[0]) + ": " + str(row[1]))

    print(len(labels_df))
    # labels_df = labels_df.drop(columns=['Unnamed: 0'])
    labels_df.to_csv('/home/amy/data/no_aug_annotated_labels.csv')


def process_labels():
    annotations_df = pd.read_csv(
        '/home/amy/elvo-analysis/annotations.csv')
    # annotations_df = pd.read_csv(
    #         '/Users/haltriedman/Desktop/annotations.csv')
    annotations_df = annotations_df.drop(['created_by',
                                          'created_at',
                                          'ROI Link',
                                          'Unnamed: 10',
                                          'Mark here if Matt should review'],
                                         axis=1)
    annotations_df = annotations_df[
        annotations_df.red1 == annotations_df.red1]
    logging.info(annotations_df)
    return annotations_df


def run_preprocess():
    configure_logger()
    annotations_df = process_labels()
    create_labels(annotations_df)
    #create_chunks(annotations_df)


if __name__ == '__main__':
    run_preprocess()