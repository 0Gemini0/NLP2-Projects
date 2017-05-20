from libitg import *
import copy
import numpy as np
import random
from scipy.misc import logsumexp
from training.model import  weight_function

"contains all functions from the MLE part of the LV-CRF-Roadmap ipython notebook"


def inside_algorithm(forest: CFG, tsort: list, edge_weights: dict) -> dict:
    """Returns the inside weight of each node in log space. The inside at ROOT is the Z of the forest"""

    inside = {}

    for v in tsort:
        BS = forest.get(v)
        if not BS:  # list is empty
            inside[v] = 0  # terminal. 1 -> 0 in log semicircle
        else:
            ks = []
            inside[v] = -np.inf  # additive identity 0 -> -np.inf in log semicircle
            for e in BS:
                k = np.log(edge_weights[e])  # include weight of own edge
                for u in e.rhs:
                    k = k + inside[u]  # product becomes sum of logs
                ks.append(k)
            ks.append(inside[v])
            inside[v] = logsumexp(np.array(ks))  # sum becomes log-sum of exponents of logs
    return inside


def outside_algorithm(forest: CFG, tsort: list, edge_weights: dict, inside: dict) -> dict:
    """Returns the outside weight of each node in log space"""

    tsort = list(reversed(tsort))  # traverse nodes top-bottom
    outside = {}
    for v in tsort:
        outside[v] = [-np.inf]  # 0 -> -inf in log space
    outside[tsort[0]] = 0.0  # root (S) is one, 1 -> 0 in log space

    for v in tsort:
        for e in forest.get(v):  # the BS (incoming edges) of node v
            for u in e.rhs:  # children of v in e
                k = np.log(edge_weights[e]) + outside[v]
                for s in e.rhs:  # siblings of u in e
                    if u is not s:
                        k = k + inside[s]  # product becomes sum of logs
                outside[u].append(k)  # accumulate outside for node u

    for node in outside:
        outside[node] = logsumexp(np.array(outside[node]))  # sum becomes log-sum of exponents

    return outside


def top_sort(forest: CFG, start_label ='S') -> list:
    """Returns ordered list of nodes according to topsort order in an acyclic forest"""
    # rules = [r for r in cfg]
    for nonterminal in forest.nonterminals:
        if nonterminal.root() == Nonterminal(start_label):
            start = nonterminal
    # find the topologically sorted sequence
    ordered = [start_label]
    for nonterminal in ordered:
        rules = forest.get(nonterminal)
        for rule in rules:
            for variable in rule.rhs:
                if not variable.is_terminal() and variable not in ordered:
                    ordered.append(variable)
    return list(reversed(ordered))


def expected_feature_vector(forest: CFG, inside: dict, outside: dict, edge_features: dict) -> dict:
    """Returns an expected feature vector (here a sparse python dictionary) in log space"""
    phi = defaultdict(float)

    for e in forest:
        k = outside[e.lhs]
        for u in e.rhs:
            k = k + inside[u]  # product becomes sum of logs (but they are already in log space here)
        for key, feature in edge_features[e].iteritems():
            phi[key] += k * feature

    return phi


def inside_viterbi(forest: CFG, tsort: list, edge_weights: dict) -> dict:
    """Returns the inside max of each node in log space"""

    inside = {}

    for v in tsort:
        BS = forest.get(v)
        if not BS:  # list is empty
            inside[v] = 0  # 1 -> 0 in log space
        else:
            ks = []
            inside[v] = -np.inf  # 0 -> -1 in log space
            for e in BS:
                k = np.log(edge_weights[e])  # include weight of own edge
                for u in e.rhs:
                    k = k + inside[u]  # product becomes sum of logs (but they are already logs)
                ks.append(k)
                ks.append(inside[v])
            inside[v] = np.amax(np.array(ks))  # sum becomes max, max becomes max in log space
    return inside


def stochastic_gradient_descent_step(batch: list, features: list, learning_rate: float, wmap:dict,
                                     start_labels = ["D_i(x)", "D_i(x,y)"], reg=False):
    """
    Performs one SGD step on a batch of featurized DiX and DiXY forests
        :param batch: list of forests
        :param features: list of features
        :param learning_rate: learning rate for update
        :param wmap: current weights
        :param start_labels: ordered list of start labels of the two forests
        :param reg: whether or nog to regularize the update
        :return wmap2: updated weights
        :return loss: batch log likelihood
    """

    # prelims
    gradient = defaultdict(float)
    wmap2 = defaultdict(float)
    loss = 0.0

    # process the entire batch
    for forests, feats in zip(batch, features):
        expected_features = []
        Z = []
        i = 0

        for forest, feat in zip(forests, feats):
            edge_weights = {}
            for edge in forest:
                # weight of each edge in the forest based on its features and the current wmap
                edge_weights[edge] = weight_function(edge, feat[edge], wmap)

            # compute expected feature vector for this forest
            tsort = top_sort(forest, start_labels[i])
            inside = inside_algorithm(forest, tsort, edge_weights)
            outside = outside_algorithm(forest, tsort, edge_weights, inside)
            expected_features.append(expected_feature_vector(forest, inside, outside, feat))

            # store Z
            Z.append(inside[tsort[-1]])  # the normalizer Z is the inside value at the root of the forest

            i += 1

        # consider the intersection of features of the two forests
        keys = set(expected_features[0].keys())
        keys.update(expected_features[1].keys())

        # accumulate gradients
        for key in keys:
            gradient[key] += expected_features[1][key] - expected_features[0][key]

        # accumulate loss
        loss += Z[1] - Z[0]

    # update the weights
    if reg:
        # TODO
        pass
    else:
        for key in gradient:
            wmap2[key] = wmap[key] + learning_rate * gradient[key]

    return wmap2, loss





