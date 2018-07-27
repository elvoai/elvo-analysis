import csv
import numpy as np
import random
from google.cloud import storage
import pandas as pd
from lib import cloud_management
import pickle
import logging

train_ids = {}
val_ids = {}
test_ids = {'9UIAZ2U1711BN4IW': '',
            'HXLMZWH3SFX3SPAN': '',
            'IAUKV5R644JZFD55': '',
            'ILNTKMBVTXNXURGV': '',
            'JJMENP4QE4CSXSHV': '',
            'JWKB7SHIBYWSEVMC': '',
            'KOE9CU24WK2TUQ43': '',
            'LGFNFIWO2ZEQYK36': '',
            'LINKQMUO9DQ43BNH': '',
            'LUVMEPI5JWYL67RF': '',
            'NHXCOHZ4HH53NLQ6': '',
            'RKBSU42WA7AY22E7': '',
            'RSKIY1U4X5QAUAAK': '',
            'SMGWMDYTYR8ZB3F5': '',
            'TRRYZ5WXYHUMTPCQ': '',
            'WWEFFBIMLZ3KLQVZ': '',
            'XSSFSN7XYAV4E3OA': '',
            'Z3AINLH4Y07ITBRR': '',
            'ZUEK5YSS7CITVWIP': '',
            '93BHW6GWBXMCXKZ': '',
            'W121FB8QX3LKCC5': '',
            'SPX5RHIM3I9G59H': '',
            'Y7TEI4R9A38060M': '',
            'CRLLJI0HYKR44H9': '',
            'J7OYZ0VL03RR0MG': '',
            'XM6CIDICOUPNBV9': '',
            'K138ZZNJBPCUJZU': '',
            '9PMFHK7Q3UGW0UM': '',
            'AZ23ZIFCYD9G1BN': '',
            'JJAET882O5AO7DD': '',
            '6WVZJW8VCKWPIGS': '',
            'WXRN2SWK763NZKT': '',
            'VIDM8DUZF5FBL5B': '',
            '8JTIFBJ85TJF7WZ': '',
            'E12QSRZG7DZDO3W': '',
            '8IG0XH3NO0SED7G': '',
            'FY5Y1WZYUR9OM85': '',
            'D5TB0LC9Q6ERYXP': '',
            'PZ3PAP7C8T6YVV9': '',
            'E2QR05XTWSSCB7T': '',
            'H0MSX6TSVLWG2LW': '',
            '0S14KBH0LQNHSIT': '',
            'WG2UEF2X6Q42ZJP': '',
            '450HUVNTNQY091H': '',
            '1TKIFTWTZB41S0N': '',
            '9SVLIU96EDGDX6W': '',
            'U0WYP8EFJLQG305': '',
            'MYSQVGRGT0FMC3E': '',
            'FHXDCGURXJBXD2F': '',
            'J8K098OLZFZH6LW': '',
            '2VEFNSOJ0IHTDQL': '',
            'UBS0O3YFB5ORS31': ''}

pos_train = 0
neg_train = 0
pos_val = 0
neg_val = 0
pos_test = 19
neg_test = 0


def configure_logger():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


configure_logger()

# Access Google Cloud Storage
gcs_client = storage.Client.from_service_account_json(
    '/home/harold_triedman/elvo-analysis/credentials/client_secret.json'
    # 'credentials/client_secret.json'
)
bucket = gcs_client.get_bucket('elvos')

# Get label data from Google Cloud Storage
blob = storage.Blob('augmented_annotated_labels.csv', bucket)
blob.download_to_filename('tmp/augmented_annotated_labels.csv')
prelim_label_data = {}
with open('tmp/augmented_annotated_labels.csv', 'r') as pos_file:
    reader = csv.reader(pos_file, delimiter=',')
    for row in reader:
        if row[1] != 'Unnamed: 0.1':
            prelim_label_data[row[1]] = int(row[2])
            # prelim_label_data[row[2]] = int(row[3])

# Get all of the positives from the label data
positive_label_data = {}
logging.info('getting 12168 positive labels')
for id_, label in list(prelim_label_data.items()):
    if label == 1 and '_' in id_:
        positive_label_data[id_] = label

positive_train_label_data = {}
positive_val_label_data = {}
positive_test_label_data = {}

# split positives into train/test/val by ID
for i, id_ in enumerate(list(positive_label_data.keys())):
    if i % 24 == 0:
        seed = random.randint(1, 100)
        meta_id = id_[:16]
        stripped_id = id_[:-1]
        if seed > 20:
            positive_train_label_data[id_] = 1
            for j in range(2, 25):
                positive_train_label_data[stripped_id + str(j)] = 1
            train_ids[meta_id] = ''
            pos_train += 1
        elif seed > 10:
            positive_val_label_data[id_] = 1
            for j in range(2, 25):
                positive_val_label_data[stripped_id + str(j)] = 1
            val_ids[meta_id] = ''
            pos_val += 1
        else:
            positive_test_label_data[id_] = 1
            for j in range(2, 25):
                positive_test_label_data[stripped_id + str(j)] = 1
            if meta_id not in test_ids:
                test_ids[meta_id] = ''
                pos_test += 1

# Get 14500 random negatives from the label data to feed into our generator
negative_train_label_data = {}
negative_val_label_data = {}
negative_test_label_data = {}

logging.info("getting 14500 random negative labels")
negative_counter = 0

# split negatives into train/test/val by
# previous splits in positive/new random number
while negative_counter < 14500:
    id_, label = random.choice(list(prelim_label_data.items()))
    if label == 0:
        if negative_counter % 500 == 0:
            logging.info(f'gotten {negative_counter} labels so far')

        meta_id = id_[:16]
        if meta_id in train_ids:
            negative_train_label_data[id_] = label

        elif meta_id in val_ids:
            negative_val_label_data[id_] = label

        elif meta_id in test_ids:
            negative_test_label_data[id_] = label

        else:
            seed = random.randint(1, 100)
            if seed > 20:
                negative_train_label_data[id_] = label
                train_ids[meta_id] = ''
                neg_train += 1
            elif seed > 10:
                negative_val_label_data[id_] = label
                val_ids[meta_id] = ''
                neg_val += 1
            else:
                negative_test_label_data[id_] = label
                test_ids[meta_id] = ''
                neg_test += 1
        del prelim_label_data[id_]
        negative_counter += 1

# save train/val/test split by IDs
logging.info("saving train/val/test metadata IDs")
logging.info(f"training brains:   {pos_train} ELVO positive, {neg_train} ELVO negative\n"
             f"validation brains: {pos_val} ELVO positive, {neg_val} ELVO negative\n"
             f"testing brains:    {pos_test} ELVO positive, {neg_test} ELVO negative")
pd.DataFrame.from_dict(train_ids, 'index').to_csv('train_ids.csv')
pd.DataFrame.from_dict(val_ids, 'index').to_csv('val_ids.csv')
pd.DataFrame.from_dict(test_ids, 'index').to_csv('test_ids.csv')

train_chunks = []
train_labels = []
val_chunks = []
val_labels = []
test_chunks = []
test_labels = []

# get positive train chunks and labels
i = 1
for id_, label in list(positive_train_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/positive/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        train_chunks.append(arr)
        train_labels.append(label)
logging.info(f'{i} total positive training chunks')

# get negative train chunks and labels
i = 1
for id_, label in list(negative_train_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/negative/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        train_chunks.append(arr)
        train_labels.append(label)
logging.info(f'{i} total negative chunks')

# get positive val chunks and labels
i = 1
for id_, label in list(positive_val_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/positive/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        val_chunks.append(arr)
        val_labels.append(label)
logging.info(f'{i} total positive validation chunks')

# get negative val chunks and labels
i = 1
for id_, label in list(negative_val_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/negative/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        val_chunks.append(arr)
        val_labels.append(label)
logging.info(f'{i} total negative chunks')

# get positive test chunks and labels
i = 1
for id_, label in list(positive_test_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/positive/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        test_chunks.append(arr)
        test_labels.append(label)
logging.info(f'{i} total positive validation chunks')

# get negative test chunks and labels
i = 1
for id_, label in list(negative_test_label_data.items()):
    if i % 500 == 0:
        logging.info(f'got chunk {i}')
    i += 1
    blob = bucket.get_blob('chunk_data/normal/negative/' + id_ + '.npy')
    arr = cloud_management.download_array(blob)
    if arr.shape == (32, 32, 32):
        arr = np.expand_dims(arr, axis=-1)
        test_chunks.append(arr)
        test_labels.append(label)
logging.info(f'{i} total negative chunks')

# shuffle training chunk order
tmp = list(zip(train_chunks, train_labels))
random.shuffle(tmp)
train_chunks, train_labels = zip(*tmp)

# shuffle val chunk order
tmp = list(zip(val_chunks, val_labels))
random.shuffle(tmp)
val_chunks, val_labels = zip(*tmp)

# shuffle test chunk order
tmp = list(zip(test_chunks, test_labels))
random.shuffle(tmp)
test_chunks, test_labels = zip(*tmp)

# Turn into numpy arrays
full_x_train = np.asarray(train_chunks)
full_y_train = np.asarray(train_labels)
x_val = np.asarray(val_chunks)
y_val = np.asarray(val_labels)
x_test = np.asarray(test_chunks)
y_test = np.asarray(test_labels)

logging.info(f'{len(train_chunks)} total chunks to train with')
logging.info(f'full training data: {full_x_train.shape}, {full_y_train.shape}')
logging.info(f'full validation data: {x_val.shape}, {y_val.shape}')
logging.info(f'full test data: {x_test.shape}, {y_test.shape}')

# save as pickle to preserve order of train/val/test labels
full_arr = np.array([full_x_train,
                     full_y_train,
                     x_val,
                     y_val,
                     x_test,
                     y_test])
with open('chunk_data_separated_ids.pkl', 'wb') as outfile:
    pickle.dump(full_arr, outfile, pickle.HIGHEST_PROTOCOL)
