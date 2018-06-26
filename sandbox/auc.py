from keras import backend as K
from keras.models import Model, load_model
from keras.applications.resnet50 import ResNet50
import keras.metrics as metrics
from ml.generators.mip_generator import MipGenerator
import numpy as np

from sklearn.metrics import roc_curve, auc, classification_report
import matplotlib.pyplot as plt


def sensitivity(y_true, y_pred):
    true_positives = K.sum(K.round(K.clip(y_true * y_pred, 0, 1)))
    possible_positives = K.sum(K.round(K.clip(y_true, 0, 1)))
    return true_positives / (possible_positives + K.epsilon())


def specificity(y_true, y_pred):
    true_negatives = K.sum(K.round(K.clip((1 - y_true) * (1 - y_pred), 0, 1)))
    possible_negatives = K.sum(K.round(K.clip(1 - y_true, 0, 1)))
    return true_negatives / (possible_negatives + K.epsilon())


metrics.sensitivity = sensitivity
metrics.specificity = specificity


def get_pred():
    model_1 = ResNet50(weights='imagenet', include_top=False)
    model_2 = load_model('sandbox/stage_1_resnet')
    model = Model(input=model_1.input, output=model_2(model_1.output))
    model.compile(optimizer='adam',
                  loss='binary_crossentropy',
                  metrics=['accuracy'])

    gen = MipGenerator(
        dims=(220, 220, 3),
        batch_size=4,
        augment_data=False,
        extend_dims=False,
        test=True,
        split_test=True,
        shuffle=True,
        split=0.2
    )

    result = model.evaluate_generator(
        generator=gen.generate(),
        steps=gen.get_steps_per_epoch(),
        verbose=1
    )
    print(result)

    result = model.predict_generator(
        generator=gen.generate(),
        steps=gen.get_steps_per_epoch(),
        verbose=1
    ).ravel()

    np.save('sandbox/pred.npy', result)


def get_validation():
    gen = MipGenerator(
        dims=(220, 220, 3),
        batch_size=4,
        augment_data=False,
        extend_dims=False,
        test=True,
        split_test=True,
        shuffle=True,
        split=0.2
    )

    result = []
    generate = gen.generate()
    print(gen.get_steps_per_epoch())
    for i in range(gen.get_steps_per_epoch()):
        print(i)
        data, labels = next(generate)
        result.append(labels)
    result = np.array(result).ravel()
    np.save('sandbox/val.npy', result)


def sensitivity_2(y_true, y_pred):
    true_positives = np.sum(np.round(np.clip(y_true * y_pred, 0, 1)))
    possible_positives = np.sum(np.round(np.clip(y_true, 0, 1)))
    return true_positives / (possible_positives + 1e-07)


def specificity_2(y_true, y_pred):
    true_negatives = np.sum(np.round(np.clip((1 - y_true) *
                                             (1 - y_pred), 0, 1)))
    possible_negatives = np.sum(np.round(np.clip(1 - y_true, 0, 1)))
    return true_negatives / (possible_negatives + 1e-07)


def get_auc():
    true_data = np.load('sandbox/val.npy')
    pred_data = np.load('sandbox/pred.npy')
    fpr_keras, tpr_keras, thresholds_keras = roc_curve(true_data, pred_data)
    auc_keras = auc(fpr_keras, tpr_keras)
    print(sensitivity_2(true_data, pred_data))
    print(specificity_2(true_data, pred_data))
    target_names = ['No', 'Yes']
    report = classification_report(true_data,
                                   np.where(pred_data > 0.5, 1.0, 0.0),
                                   target_names=target_names)
    print(report)
    plt.figure(1)
    plt.plot([0, 1], [0, 1], 'k--')
    plt.plot(fpr_keras, tpr_keras,
             label='Keras (area = {:.3f})'.format(auc_keras))
    plt.xlabel('False positive rate')
    plt.ylabel('True positive rate')
    plt.title('ROC curve')
    plt.legend(loc='best')
    plt.show()


get_pred()
# get_validation()
get_auc()