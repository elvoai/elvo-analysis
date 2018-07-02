import logging
import io
from tensorflow.python.lib.io import file_io
import imageio
import numpy as np
from google.cloud import storage


def authenticate():
    return storage.Client.from_service_account_json(
        './credentials/client_secret.json'
    )


def download_array(blob: storage.Blob) -> np.ndarray:
    in_stream = io.BytesIO()
    blob.download_to_file(in_stream)
    in_stream.seek(0)  # Read from the start of the file-like object
    return np.load(in_stream)


def upload_png(arr: np.ndarray, id: str, type: str, bucket: storage.Bucket):
    """Uploads MIP PNGs to gs://elvos/mip_data/<patient_id>/<scan_type>_mip.png.
    """
    try:
        out_stream = io.BytesIO()
        imageio.imwrite(out_stream, arr, format='png')
        out_filename = f'mip_data/{id}/{type}_mip.png'
        print(out_filename)
        out_blob = storage.Blob(out_filename, bucket)
        out_stream.seek(0)
        out_blob.upload_from_file(out_stream)
        print("Saved png file.")
    except Exception as e:
        logging.error(f'for patient ID: {id} {e}')


def save_npy_to_cloud(arr: np.ndarray, id: str, type: str):
    """Uploads MIP .npy files to gs://elvos/mip_data/from_numpy/<patient
        id>_mip.npy
    """
    try:
        print(f'gs://elvos/mip_data/from_{type}/{id}_mip.npy')
        np.save(file_io.FileIO(f'gs://elvos/mip_data/from_{type}/'
                               f'{id}_mip.npy', 'w'), arr)
    except Exception as e:
        logging.error(f'for patient ID: {id} {e}')

def save_stripped_npy(arr: np.ndarray, id: str, type: str):
    """Uploads mipped and stripped .npy files to
        gs://elvos/stripped_data/{view}/<patient id>_mip.npy"""
    try:
        print(f'gs://elvos/stripped_data/{type}/{id}_mip.npy')
        np.save(file_io.FileIO(f'gs://elvos/stripped_data/{type}/'
                               f'{id}_mip.npy', 'w'), arr)
    except Exception as e:
        logging.error(f'for patient ID: {id} {e}')