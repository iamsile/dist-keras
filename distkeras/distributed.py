"""
Distributed module. This module will contain all distributed classes and
methods.
"""

## BEGIN Imports. ##############################################################

from itertools import chain
from itertools import tee

from keras.models import model_from_json
from keras.optimizers import RMSprop
from keras.utils import np_utils

from pyspark.mllib.linalg import DenseVector
from pyspark.sql import Row

import numpy as np

## END Imports. ################################################################

## BEGIN Utility functions. ####################################################

def to_vector(x, n_dim):
    vector = np.zeros(n_dim)
    vector[x] = 1.0

    return vector

## END Utility functions. ######################################################

class Transformer(object):

    def transform(self, data):
        raise NotImplementedError


class Predictor(Transformer):

    def __init__(self, keras_model):
        self.model = keras_model.to_json()

    def predict(self, data):
        raise NotImplementedError


class Trainer(object):

    def __init__(self, keras_model):
        self.master_model = keras_model.to_json()

    def train(self, data):
        raise NotImplementedError


class EnsembleTrainer(Trainer):

    def __init__(self, keras_model, num_models=2, features_col="features",
                 label_col="label", label_transformer=None):
        super(EnsembleTrainer, self).__init__(keras_model)
        self.num_models = num_models
        self.features_column = features_col
        self.label_column = label_col
        self.label_transformer = label_transformer

    def train(self, data):
        # Repartition the data to fit the number of models.
        data = data.repartition(self.num_models)
        # Allocate an ensemble worker.
        worker = EnsembleTrainerWorker(keras_model=self.master_model,
                                       features_col=self.features_column,
                                       label_col=self.label_column,
                                       label_transformer=self.label_transformer)
        # Train the models, and collect them as a list.
        models = data.mapPartitions(worker.train).collect()

        return models

class EnsembleTrainerWorker(object):

    def __init__(self, keras_model, features_col, label_col, label_transformer):
        self.model = keras_model
        self.features_column = features_col
        self.label_column = label_col
        self.label_transformer = label_transformer

    def train(self, iterator):
        # Deserialize the Keras model.
        model = model_from_json(self.model)
        # Initialize empty feature and label lists.
        X = []
        Y = []
        # Construct the feature and label vectors
        try:
            # Check if a label transformer is available.
            if not self.label_transformer == None:
                for row in iterator:
                    X.append(row[self.features_column])
                    Y.append(self.label_transformer(row[self.label_column]))
            else:
                for row in iterator:
                    X.append(row[self.features_column])
                    Y.append(row[self.label_column])
            X = np.array(X)
            Y = np.array(Y)
        except TypeError:
            pass
        # TODO Add compilation parameters.
        model.compile(loss='categorical_crossentropy',
                      optimizer=RMSprop(),
                      metrics=['accuracy'])
        # Fit the model with the data.
        history = model.fit(X, Y, nb_epoch=1)
        partitionResult = (history, model.to_json())

        return iter([partitionResult])