import numpy as np
import tensorflow as tf
import random
from pprint import pprint
from utils import iterate_minibatches, prepare_data, smart_reader, bitext_reader
import pickle
import math


class NeuralIBM1Trainer:
  """
  Takes care of training a model with SGD.
  """
  
  def __init__(self, model, train_e_path, train_f_path, 
               dev_e_path, dev_f_path, dev_wa,
               test_e_path, test_f_path, test_wa,
               num_epochs=5, 
               batch_size=16, max_length=30, lr=0.1, lr_decay=0.001, session=None):
    """Initialize the trainer with a model."""

    self.model = model
    self.train_e_path = train_e_path
    self.train_f_path = train_f_path
    self.dev_e_path = dev_e_path
    self.dev_f_path = dev_f_path
    self.dev_wa = dev_wa
    self.test_e_path = test_e_path
    self.test_f_path = test_f_path
    self.test_wa = test_wa
    
    self.num_epochs = num_epochs
    self.batch_size = batch_size
    self.max_length = max_length
    self.lr = lr
    self.lr_decay = lr_decay
    self.session = session

    self.epoch_loss = []
    self.val_loss = []
    self.val_aer = []
    self.test_aer = []
    self.epoch_kl = []
    self.epoch_ce = []
    self.save_points = 0

    print("Training with B={} max_length={} lr={} lr_decay={}".format(
        batch_size, max_length, lr, lr_decay))

    self._build_optimizer()
    
    # This loads the data into memory so that we can easily shuffle it.
    # If this takes too much memory, shuffle the data on disk
    # and use bitext_reader directly.
    self.corpus = list(bitext_reader(
        smart_reader(train_e_path), 
        smart_reader(train_f_path), 
        max_length=max_length))    
    self.dev_corpus = list(bitext_reader(
        smart_reader(dev_e_path), 
        smart_reader(dev_f_path)))
    self.test_corpus = list(bitext_reader(
        smart_reader(test_e_path),
        smart_reader(test_f_path)))
    
  def _build_optimizer(self):
    """Buid the optimizer."""
    self.lr_ph = tf.placeholder(tf.float32)
    # Uncomment this to use simple SGD instead (uses less memory, converges slower)
    #self.optimizer = tf.train.GradientDescentOptimizer(
    #  learning_rate=self.lr_ph).minimize(self.model.loss)

    # use Adam optimizer
    self.optimizer = tf.train.AdamOptimizer(
      learning_rate=self.lr_ph).minimize(self.model.loss)
    
  def train(self):
    """Trains a model."""
    
    steps = 0

    for epoch_id in range(1, self.num_epochs + 1):
      
      # shuffle data set every epoch
      print("Shuffling training data")
      random.shuffle(self.corpus)

      nantick = 0
      loss = 0.0
      kl = 0.0
      ce = 0.0
      accuracy_correct = 0
      accuracy_total = 0
      epoch_steps = 0

      for batch_id, batch in enumerate(iterate_minibatches(
          self.corpus, batch_size=self.batch_size), 1):
        
        # Dynamic learning rate, cf. Bottou (2012), Stochastic gradient descent tricks.
        lr_t = self.lr * (1 + self.lr * self.lr_decay * steps)**-1
        
        x, y = prepare_data(batch, self.model.x_vocabulary, 
                            self.model.y_vocabulary)
        
        # If you want to see the data that goes into the model during training
        # you may uncomment this.
        #if batch_id % 1000 == 0:
        #    print(" ".join([str(t) for t in x[0]]))
        #    print(" ".join([str(t) for t in y[0]]))
        #    print(" ".join([self.model.x_vocabulary.get_token(t) for t in x[0]]))
        #    print(" ".join([self.model.y_vocabulary.get_token(t) for t in y[0]]))

        # input to the TF graph
        feed_dict = { 
          self.lr_ph : lr_t,
          self.model.x : x, 
          self.model.y : y
        }
        
        # things we want TF to return to us from the computation
        fetches = {
          "optimizer"   : self.optimizer,
          "loss"        : self.model.loss,
          "acc_correct" : self.model.accuracy_correct,
          "acc_total"   : self.model.accuracy_total,
          "pa_x"        : self.model.pa_x,
          "py_xa"       : self.model.py_xa,
          "py_x"        : self.model.py_x,
          "kl"          : self.model.kl,
          "ce"          : self.model.ce
        }

        res = self.session.run(fetches, feed_dict=feed_dict)

        if math.isnan(res["loss"]):
          # enforce break on nan, don't store the model any more
          nantick += 1

        if nantick == 3:
          break

        loss += res["loss"]
        accuracy_correct += res["acc_correct"]
        accuracy_total += res["acc_total"]
        batch_accuracy = res["acc_correct"] / float(res["acc_total"])
        steps += 1
        epoch_steps += 1
        kl += res["kl"]
        ce += res["ce"]
        
        if batch_id % 100 == 0:
          print("Iter {:5d} loss {:6f} accuracy {:1.2f} lr {:1.6f} kl {:1.6f}".format(
            batch_id, res["loss"], batch_accuracy, lr_t, res["kl"]))

        # get full statistics every 2500 batches instead of every epoch
        if batch_id % 2500 == 0:

          # count the number of save points per epoch
          if epoch_id == 1:
            self.save_points += 1

          # evaluate on development set
          val_aer, val_acc, val_loss = self.model.evaluate(self.dev_corpus, self.dev_wa)

          # evaluate on test set
          test_aer, __, __ = self.model.evaluate(self.test_corpus, self.test_wa)

          # print partial Epoch loss
          print("Epoch {} iter {:5d} loss {:6f} accuracy {:1.2f} val_aer {:1.2f} val_acc {:1.2f} val_loss {:1.2f} "
                "test_aer: {:1.2f}".format(
              epoch_id,
              batch_id,
              loss / float(epoch_steps),
              accuracy_correct / float(accuracy_total),
              val_aer, val_acc, val_loss,
              test_aer))

          # save parameters
          save_path = self.model.save(self.session, path="./modelvae.ckpt")
          print("Model saved in file: %s" % save_path)

          # store some statistics
          self.epoch_loss.append(loss / float(epoch_steps))
          self.epoch_kl.append(kl / float(epoch_steps))
          self.epoch_ce.append(ce / float(epoch_steps))
          self.val_aer.append(val_aer)
          self.val_loss.append(val_loss)
          self.test_aer.append(test_aer)

          pickle.dump([self.epoch_loss, self.val_aer, self.val_loss, self.test_aer, self.epoch_kl, self.epoch_ce], open("vae_during", "wb"))

      if nantick == 3:
        break

      # final save point
      if epoch_id == 1:
        self.save_points += 1

      # evaluate on development set
      val_aer, val_acc, val_loss = self.model.evaluate(self.dev_corpus, self.dev_wa)

      # evaluate on test set
      test_aer, __, __ = self.model.evaluate(self.test_corpus, self.test_wa)

      # print Epoch loss
      print(
        "Epoch {} end, loss {:6f} accuracy {:1.2f} val_aer {:1.2f} val_acc {:1.2f} val_loss {:1.2f} test_aer {:1.2f}".format(
          epoch_id,
          loss / float(epoch_steps),
          accuracy_correct / float(accuracy_total),
          val_aer, val_acc, val_loss,
          test_aer))

      # save parameters
      save_path = self.model.save(self.session, path="./modelvae.ckpt")
      print("Model saved in file: %s" % save_path)

      # store some statistics
      self.epoch_loss.append(loss / float(epoch_steps))
      self.val_aer.append(val_aer)
      self.val_loss.append(val_loss)
      self.test_aer.append(test_aer)
      self.epoch_kl.append(kl / float(epoch_steps))
      self.epoch_ce.append(ce / float(epoch_steps))
      pickle.dump([self.epoch_loss, self.val_aer, self.val_loss, self.test_aer, self.epoch_kl, self.epoch_ce], open("vae_during", "wb"))