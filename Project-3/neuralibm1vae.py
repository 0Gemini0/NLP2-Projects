import numpy as np
import tensorflow as tf
from aer import read_naacl_alignments, AERSufficientStatistics
from utils import iterate_minibatches, prepare_data
from neuralibm1context import NeuralIBM1ModelContext
from scipy.special import gamma

# for TF 1.1
try:
    from tensorflow.contrib.keras.initializers import glorot_uniform
except:  # for TF 1.0
    from tensorflow.contrib.layers import xavier_initializer as glorot_uniform


class NeuralIBM1ModelVAE(NeuralIBM1ModelContext):
    """
    Our Neural IBM1 model with latent collocation variable trough a variational autoencoder.
    It lends the viterbi function from the context IBM1, as p_xa has the same increased size
    """

    def __init__(self, batch_size=8,
                 x_vocabulary=None, y_vocabulary=None,
                 emb_dim=32, mlp_dim=64,
                 session=None):
        super().__init__(batch_size, x_vocabulary, y_vocabulary, emb_dim, mlp_dim, session)

    def _create_weights(self):
        """Create weights for the model."""
        with tf.variable_scope("MLP") as scope:
            # a(f_(j-1)) for Beta FFNN
            self.mlp_Waf_ = tf.get_variable(
                name="Waf_", initializer=glorot_uniform(),
                shape=[self.emb_dim, self.mlp_dim])

            self.mlp_baf_ = tf.get_variable(
                name="baf_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_Waf = tf.get_variable(
                name="Waf", initializer=glorot_uniform(),
                shape=[self.mlp_dim, 1])

            self.mlp_baf = tf.get_variable(
                name="baf", initializer=tf.constant_initializer(0.0),
                shape=[1])

            # b(f_(j-1)) for Beta FFNN
            self.mlp_Wbf_ = tf.get_variable(
                name="Wbf_", initializer=glorot_uniform(),
                shape=[self.emb_dim, self.mlp_dim])

            self.mlp_bbf_ = tf.get_variable(
                name="bbf_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_Wbf = tf.get_variable(
                name="Wbf", initializer=glorot_uniform(),
                shape=[self.mlp_dim, 1])

            self.mlp_bbf = tf.get_variable(
                name="bbf", initializer=tf.constant_initializer(0.0),
                shape=[1])

            # a(f_(j, j-1)) for Kuma FFNN
            self.mlp_Waff_ = tf.get_variable(
                name="Waff_", initializer=glorot_uniform(),
                shape=[self.emb_dim * 2, self.mlp_dim])

            self.mlp_baff_ = tf.get_variable(
                name="baff_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_Waff = tf.get_variable(
                name="Waff", initializer=glorot_uniform(),
                shape=[self.mlp_dim, 1])

            self.mlp_baff = tf.get_variable(
                name="baff", initializer=tf.constant_initializer(0.0),
                shape=[1])

            # b(f_(j, j-1)) for Kuma FFNN
            self.mlp_Wbff_ = tf.get_variable(
                name="Wbff_", initializer=glorot_uniform(),
                shape=[self.emb_dim * 2, self.mlp_dim])

            self.mlp_bbff_ = tf.get_variable(
                name="bbff_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_Wbff = tf.get_variable(
                name="Wbff", initializer=glorot_uniform(),
                shape=[self.mlp_dim, 1])

            self.mlp_bbff = tf.get_variable(
                name="bbff", initializer=tf.constant_initializer(0.0),
                shape=[1])

            # latent gatent IBM1
            self.mlp_Wy_ = tf.get_variable(
                name="Wy_", initializer=glorot_uniform(),
                shape=[self.emb_dim, self.mlp_dim])

            self.mlp_by_ = tf.get_variable(
                name="by_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_Wx_ = tf.get_variable(
                name="Wx_", initializer=glorot_uniform(),
                shape=[self.emb_dim, self.mlp_dim])

            self.mlp_bx_ = tf.get_variable(
                name="bx_", initializer=tf.constant_initializer(0.0),
                shape=[self.mlp_dim])

            self.mlp_W = tf.get_variable(
                name="W", initializer=glorot_uniform(),
                shape=[self.mlp_dim, self.y_vocabulary_size])

            self.mlp_b = tf.get_variable(
                name="b", initializer=tf.constant_initializer(0.0),
                shape=[self.y_vocabulary_size])

    @staticmethod
    def beta(a, b):
        return tf.exp(tf.lgamma(a) + tf.lgamma(b) - tf.lgamma(a + b))

    def _build_model(self):
        ###############################################################################################################
        # 0. Prelims

        # first we need to know some sizes from the current input data
        batch_size = tf.shape(self.x)[0]
        longest_x = tf.shape(self.x)[1]  # longest M
        longest_y = tf.shape(self.y)[1]  # longest N

        # It's also useful to have masks that indicate what
        # values of our batch we should ignore.
        # Masks have the same shape as our inputs, and contain
        # 1.0 where there is a value, and 0.0 where there is padding.
        x_mask = tf.cast(tf.sign(self.x), tf.float32)  # Shape: [B, M]
        y_mask = tf.cast(tf.sign(self.y), tf.float32)  # Shape: [B, N]
        x_len = tf.reduce_sum(tf.sign(self.x), axis=1)  # Shape: [B]
        y_len = tf.reduce_sum(tf.sign(self.y), axis=1)  # Shape: [B]
        ###############################################################################################################
        # 1. Build an alignment model P(A | X, M, N)

        # This just gives you 1/length_x (already including NULL) per sample.
        # i.e. the lengths are the same for each word y_1 .. y_N.
        lengths = tf.expand_dims(x_len, -1)  # Shape: [B, 1]
        pa_x = tf.div(x_mask, tf.cast(lengths, tf.float32))  # Shape: [B, M]

        # We now have a matrix with 1/M values.
        # For a batch of 2 sentences, with lengths 2 and 3:
        #
        #  pa_x = [[1/2 1/2   0]
        #          [1/3 1/3 1/3]]
        #
        # But later we will need it N times. So we repeat (=tile) this
        # matrix N times, and for that we create a new dimension
        # in between the current ones (dimension 1).
        pa_x = tf.expand_dims(pa_x, 1)  # Shape: [B, 1, M]

        #  pa_x = [[[1/2 1/2   0]]
        #          [[1/3 1/3 1/3]]]
        # Note the extra brackets.

        # Now we perform the tiling:
        pa_x = tf.tile(pa_x, [1, longest_y, 1])  # [B, N, M]

        # And we expand for later use
        pa_x = tf.expand_dims(pa_x, 2)  # Shape: [B, N, 1, M]
        ###############################################################################################################
        # 2. Let's create a (source, target, target-prev) word embeddings matrix.

        # create the (source) word embeddings matrix.
        # Shape: [Vx, emb_dim] where Vx is the source vocabulary size
        x_embeddings = tf.get_variable(
            name="x_embeddings", initializer=tf.random_uniform_initializer(),
            shape=[self.x_vocabulary_size, self.emb_dim])

        # create the (target, target-prev) word embeddings matrix.
        # shape: [Vy, emb_dim]
        y_embeddings = tf.get_variable(
            name="y_embeddings", initializer=tf.random_uniform_initializer(),
            shape=[self.y_vocabulary_size, self.emb_dim])

        # This looks up the embedding vector for each word given the word IDs in self.x.
        # Shape: [B, M, emb_dim] where B is batch size, M is (longest) source sentence length.
        x_embedded = tf.nn.embedding_lookup(x_embeddings, self.x)

        # This looks up the embedding vector for each word given the word IDs in self.x.
        # Shape: [B, N, emb_dim] where B is batch size, N is (longest) target sentence length.
        y_embedded = tf.nn.embedding_lookup(y_embeddings, self.y)

        # This looks up the embedding vector for each previous target word given the word IDs in self.y.
        # Shape: [B, N, emb_dim] where B is batch size, N is (longest) target sentence length.
        y_prev = tf.multiply(tf.ones([batch_size, 1], dtype="int64"), 2)
        y_padded = tf.concat([y_prev, self.y], 1)
        y_padded = y_padded[:, 0:-1]
        y_prev = tf.nn.embedding_lookup(y_embeddings, y_padded)
        ###############################################################################################################
        # 3.1 The inference FFNN's for the (true) Beta posterior p(z|x,y) = Beta(a(y_(j-1)), b(y_(j-1)))
        #
        # For every French position this will predict the a and b parameter of the Beta distribution
        # This is used in the KL-divergence part of the ELBO for evaluation

        # MLP for a(f_(j-1))
        # reshape input to two dimensions
        mlp_input = tf.reshape(y_prev, [batch_size * longest_y, self.emb_dim])

        # Here we apply the MLP to our input.
        h = tf.matmul(mlp_input, self.mlp_Waf_) + self.mlp_baf_  # affine transformation [B * N, mlp_dim]
        h = tf.tanh(h)  # non-linearity
        h = tf.matmul(h, self.mlp_Waf) + self.mlp_baf  # affine transformation [B * N, 1]

        # Now we take the exponent of the result because a is always positive, and reshape back
        a_f = tf.sigmoid(h) * 10.0 + 0.01  # [B * N, 1]
        # a_f = tf.maximum(0.01, a_f)
        # a_f = tf.minimum(4.0, a_f)
        a_f = tf.reshape(a_f, [batch_size, longest_y])

        # MLP for b(f_(j-1))
        # We use the same input as the previous network

        # Here we apply the MLP to our input.
        h = tf.matmul(mlp_input, self.mlp_Wbf_) + self.mlp_bbf_  # affine transformation [B * N, mlp_dim]
        h = tf.tanh(h)  # non-linearity
        h = tf.matmul(h, self.mlp_Wbf) + self.mlp_bbf  # affine transformation [B * N, 1]

        # Now we take the exponent of the result because a is always positive, and reshape back
        b_f = tf.sigmoid(h) * 10.0 + 0.01  # [B * N, 1]
        # b_f = tf.maximum(0.01, b_f)
        # b_f = tf.minimum(4.0, b_f)
        b_f = tf.reshape(b_f, [batch_size, longest_y])
        ###############################################################################################################
        # 3.2 The inference FFNN's for the (approximate) Kuma posterior q(z|x,y) = Kuma(a(y_j, y_(j-1)), b(y_j, y_(j-1))
        #
        # For every French position given a French word and a previous French word this will predict a and b of Kuma
        # These parameters are used to define the inverse CDF of the Kuma distribution to draw a sample z ~ Kuma(a,b)
        # This sample will subsequently be used as the s parameter of a latent gatent neural IBM 1

        # concatenate french embeddings with the previous french embeddings
        y_cur_prev = tf.concat([y_embedded, y_prev], 2)

        # MLP for a(y_j, y_(j-1))
        # reshape input to two dimensions
        mlp_input = tf.reshape(y_cur_prev, [batch_size * longest_y, self.emb_dim * 2])

        # Here we apply the MLP to our input.
        h = tf.matmul(mlp_input, self.mlp_Waff_) + self.mlp_baff_  # affine transformation [B * N, mlp_dim]
        h = tf.tanh(h)  # non-linearity
        h = tf.matmul(h, self.mlp_Waff) + self.mlp_baff  # affine transformation [B * N, 1]

        # Now we take the exponent of the result because a is always positive, and reshape back
        a_ff = tf.sigmoid(h) * 10.0 + 0.01  # [B * N, 1]
        # a_ff = tf.maximum(0.01, a_ff)
        # a_ff = tf.minimum(4.0, a_ff)
        a_ff = tf.reshape(a_ff, [batch_size, longest_y])

        # MLP for b(y_j, y_(j-1)
        # We use the same input as the previous network

        # Here we apply the MLP to our input.
        h = tf.matmul(mlp_input, self.mlp_Wbff_) + self.mlp_bbff_  # affine transformation [B * N, mlp_dim]
        h = tf.tanh(h)  # non-linearity
        h = tf.matmul(h, self.mlp_Wbff) + self.mlp_bbff  # affine transformation [B * N, 1]

        # Now we take the exponent of the result because a is always positive, and reshape back
        b_ff = tf.sigmoid(h) * 10.0 + 0.01  # [B * N, 1]
        # b_ff = tf.maximum(0.01, b_ff)
        # b_ff = tf.minimum(4.0, b_ff)
        b_ff = tf.reshape(b_ff, [batch_size, longest_y])
        ###############################################################################################################
        # 3.3 Sample s ~ Kuma(a(y_j, y_(j-1)), b(y_j, y_(j-1)) by indexing the inverse CDF of Kuma with u ~ U[0,1]

        # uniform sample
        u = tf.random_uniform([batch_size, longest_y], maxval=1.0)  # [B, N]

        # sampled s for every target position
        s = tf.pow((1 - tf.pow(u, (1 / b_ff))), (1/a_ff))  # [B, N]

        # Expand and tile s to get a gate value for every source alignment in mlp dimensions
        s = tf.expand_dims(s, 2)  # [B, N, 1]
        s = tf.expand_dims(s, 2)  # [B, N, 1, 1]
        s = tf.tile(s, [1, 1, longest_x, self.mlp_dim])  # [B, N, M, mlp_dim]

        # inverted s
        s_inv = 1.0 - s
        ###############################################################################################################
        # 4.1 Hidden layers of the generative model.
        #
        # Now we run our *generative* latent gatent ibm1 using the sampled s from the *inference* networks
        # A similar network as in task 2 (collocation) is utilized, only with a softmax layer over the full model
        # The result will be p(y_j|x_(a_j), y_(j-1), s_j)

        # reshape input to two dimensions
        r_x = tf.reshape(x_embedded, [batch_size * longest_x, self.emb_dim])  # [B * M, emb_dim]
        r_y = tf.reshape(y_prev, [batch_size * longest_y, self.emb_dim])  # [B * N, emb_dim]

        # hidden layer transformations
        h_x = tf.matmul(r_x, self.mlp_Wx_) + self.mlp_bx_  # affine transformation, [B * M, mlp_dim]
        h_x = tf.tanh(h_x)  # non-linearity
        h_y = tf.matmul(r_y, self.mlp_Wy_) + self.mlp_by_  # affine transformation, [B * N, mlp_dim]
        h_y = tf.tanh(h_y)  # non-linearity
        ###############################################################################################################
        # 4.2 Tricky multiplication of h_x and h_y with gate value s.
        #
        # For every target position we now consider M possible alignments with a source type with the same gate value s
        # Furthermore we consider M times the same previous target type with gate value (1-s).
        # With 4-dimensional elementwise multiplication we can achieve this.

        # reshape h_x to correct dimensions for multiplication
        h_x = tf.reshape(h_x, [batch_size, 1, longest_x, self.mlp_dim])  # [B, 1, M, mlp_dim]
        h_x = tf.tile(h_x, [1, longest_y, 1, 1]) # [B, N, M, mlp_dim]

        # Weigh the hidden layer of source types with gate value s
        h_x = tf.multiply(s, h_x)  # [B, N, M, mlp_dim]

        # reshape h_y to correct dimensions for multiplication
        h_y = tf.reshape(h_y, [batch_size, longest_y, 1, self.mlp_dim])  # [B, N, 1, mlp_dim]
        h_y = tf.tile(h_y, [1, 1, longest_x, 1])  # [B, N, M, mlp_dim]

        # Weigh the hidden layer of previous target types with gate value s
        h_y = tf.multiply(s_inv, h_y)
        ###############################################################################################################
        # 4.3 Softmax layer of the latent gatent neural IBM 1

        # reshape input to two dimensions
        r_xy = tf.reshape(h_x + h_y, [batch_size * longest_y * longest_x, self.mlp_dim])  # [B * N * M, mlp_dim]
        r_xy = tf.matmul(r_xy, self.mlp_W) + self.mlp_b  # affine transformation, [B * N * M, Vy]

        # Now we perform a softmax which operates on a per-row basis.
        py_xys = tf.nn.softmax(r_xy)
        py_xys = tf.reshape(py_xys, [batch_size, longest_y, longest_x, self.y_vocabulary_size])  # [B, N, M, Vy]
        ###############################################################################################################
        # 4.4 Marginalise alignments: \sum_a P(a|x) P(Y|x, y, s, a)

        # Here comes a rather fancy matrix multiplication.
        # Note that tf.matmul is defined to do a matrix multiplication
        # [N, M] @ [M, Vy] for each item in the first dimension B.
        # So in the final result we have B matrices [N, Vy], i.e. [B, N, Vy].
        #
        # We matrix-multiply:
        #   pa_x       Shape: [B, N, 1, *M*]
        # and
        #   py_xys      Shape: [B, N, *M*, Vy]
        # to get
        #   py_xs  Shape: [B, N, 1, Vy]
        #
        # Which is simply one probability vector for every french position, which we require
        #
        # Note: P(y|x, s) = prod_j p(y_j|x, s) = prod_j sum_aj p(a_j|m)p(y_j|x_aj, y_(j-1), s_j)
        py_xs = tf.matmul(pa_x, py_xys)  # Shape: [B, N, 1, Vy]
        py_xs = tf.reshape(py_xs, [batch_size, longest_y, self.y_vocabulary_size])  # shape: [B, N, Vy]
        ###############################################################################################################
        # 5 Prediction

        # This calculates the accuracy, i.e. how many predictions we got right.
        predictions = tf.argmax(py_xs, axis=2)
        acc = tf.equal(predictions, self.y)
        acc = tf.cast(acc, tf.float32) * y_mask
        acc_correct = tf.reduce_sum(acc)
        acc_total = tf.reduce_sum(y_mask)
        acc = acc_correct / acc_total
        ###############################################################################################################
        # 6 Loss of the model
        #
        # The loss of the model is the negative MC estimate of the ELBO of py_x.
        # The cross entropy given by Tensorflow is the negative MC estimate of the log-likelihood
        # of py_xs, which forms the first part of this loss.
        # The second part of the negative ELBO is the KL divergence between the Kuma and Beta distribution
        # with the parameters we got from the inference networks

        cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
            labels=tf.reshape(self.y, [-1]),
            logits=tf.log(tf.maximum(1.0e-10, tf.reshape(py_xs, [batch_size * longest_y, self.y_vocabulary_size]))),
            name="logits"
        )

        # sum the cross entropy per sentence and take the mean of the batch
        cross_entropy = tf.reshape(cross_entropy, [batch_size, longest_y])
        cross_entropy = tf.reduce_sum(cross_entropy * y_mask, axis=1)
        cross_entropy = tf.reduce_mean(cross_entropy, axis=0)

        # beta_a = a_f, beta_b = b_f, kuma_a = a_ff, kuma_b = b_ff
        kl_divergence = tf.multiply(tf.div(a_ff - a_f, a_ff), -np.euler_gamma - tf.digamma(b_ff) - tf.div(1.0, b_ff)) \
                        + tf.log(tf.multiply(a_ff, b_ff)) + tf.lgamma(a_f) + tf.lgamma(b_f) - tf.lgamma(a_f + b_f) - \
                        tf.div(b_ff - 1, b_ff) + \
                        tf.multiply(tf.multiply(b_f - 1, b_ff),
                                    tf.multiply(tf.div(1.0, 1 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(1.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 2 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(2.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 3 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(3.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 4 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(4.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 5 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(5.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 6 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(6.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 7 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(7.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 8 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(8.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 9 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(9.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 10 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(10.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 11 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(11.0, a_ff), b_ff)) +
                                    tf.multiply(tf.div(1.0, 12 + tf.multiply(a_ff, b_ff)),
                                                self.beta(tf.div(12.0, a_ff), b_ff)))  # [B, N]

        # ensure the kl is never negative per word
        kl_divergence = tf.maximum(1.0e-10, kl_divergence)

        # sum the kl divergence per sentence and take the mean of the batch
        kl_divergence = tf.reduce_sum(kl_divergence * y_mask, axis=1)  # [B]
        kl_divergence = tf.reduce_mean(kl_divergence, axis=0)

        # the negative ELBO/loss is now just the cross entropy plus the kl divergence
        loss = cross_entropy + kl_divergence
        ###############################################################################################################
        # 7. Values to return
        self.ce = cross_entropy
        self.kl = kl_divergence
        self.pa_x = pa_x
        self.py_xa = py_xys  # Kept names consistent to be able to use with same trainer class
        self.py_x = py_xs
        self.loss = loss
        self.predictions = predictions
        self.accuracy = acc
        self.accuracy_correct = tf.cast(acc_correct, tf.int64)
        self.accuracy_total = tf.cast(acc_total, tf.int64)
        ###############################################################################################################
