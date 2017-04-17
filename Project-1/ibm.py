import random
import numpy as np
import math
import time

class IBM:

    IBM1 = 'ibm1'
    IBM2 = 'ibm2'
    

    def _init_(self, transProbs, model = "ibm1", method = "uniform", path = ""):
        self.model = model
        if self.model == IBM1:
            self.uniform_init(transProbs)
        elif self.model == IBM2:
            if method == "uniform":
                # uniform parameter initialization
                self.uniform_init(transProbs)
            elif method == "random":
                # do some random init
                self.random_init
            elif method == "ibm-1":
                # load or train ibm-1 as init step
                if path is not "":
                    self.transProbs = cPickle.load(open(path, 'rb'))
                else:
                    print "provide a path to ibm-1 parameters"
        else:
            print "invalid model"
           
        
    def uniform_init(self, transProbs):
        trans = {}
        for key in transProbs:
            trans[key] = {}
            vocabSize = len(transProbs[key].keys())
            for secKey in transProbs[key]:
                trans[key][secKey] = 1.0 / vocabSize
        self.transProbs = trans

    def random_init(self, transProbs):
        trans = {}
        for key in transProbs:
            trans[key] = {}
            vocabSize = len(transProbs[key].keys())
            for secKey in transProbs[key]:
                trans[key][secKey] = random.random()
            normalizer = sum(trans[key].itervalues())
            trans[key] = {k: v / normalizer for k, v in trans[key].iteritems()}
        self.transProbs = trans

    def vogel_index(self,i,j,I,J):
        # get the Vogel count index
        return math.floor(i - (j+1.0) * I / J)      

    def train_ibm(self, pairs, termination_criteria, threshold, transProbs = False, model = "ibm1"):
        # trains an ibm 1 model
        self.model = model
        converged = False
        logLikelihood = []
        if not transProbs:
            transProbs = self.transProbs # initialize_ibm(transProbs)
        else:
            self.uniform_init(transProbs)
            transProbs = self.transProbs
            
        if self.model == self.IBM2:
            # initialize vogel count parameter vector
            countsVogel = {}
            probsVogel = {}
            for pair in pairs:
                I = len(pair[0]) # english sentence length
                J = len(pair[1]) # french sentence length
                for i, enWord in enumerate(pair[0]):
                    for j, frWord in enumerate(pair[1]):
                        countsVogel[self.vogel_index(i,j,I,J)] = 0.0 # check: do we need j + 1 cuz null  
            length = len(countsVogel.keys())
            for key in countsVogel:
                probsVogel[key] = 1.0 / length
            
        while (not converged):
            start = time.time()
            logLike = 0

            # set all counts for the translation model to zero
            counts = {}
            countsEnglish = {}
            for key in transProbs:
                counts[key] = {}
                countsEnglish[key] = 0.0
                for secKey in transProbs[key]:
                    counts[key][secKey] = 0.0

            # Expectation - step
            print "E"
            for pair in pairs:
                I = len(pair[0]) # english sentence length
                J = len(pair[1]) # french sentence length
                
                #if self.model == self.IBM2:
                #     logLike += #log of IBM2 alignment probability

                logLike += -(J * np.log(I+1))
                for j, fWord in enumerate(pair[1]):
                    # calculate the normalizer of the posterior probability of this french word
                    normalizer = 0.0
                    normalizerVogel = 0.0
                    for i, eWord in enumerate(pair[0]):
                        if self.model == self.IBM2:
                            normalizer += transProbs[eWord][fWord] * probsVogel[self.vogel_index(i,j,I,J)]
                            normalizerVogel += probsVogel[self.vogel_index(i,j,I,J)]
                        else:
                            normalizer += transProbs[eWord][fWord]
                            

                    logLike += np.log(normalizer)
                    # get the expected counts based on the posterior probabilities
                    for i, eWord in enumerate(pair[0]):
                        if self.model == self.IBM2:
                            delta = probsVogel[self.vogel_index(i,j,I,J)] * transProbs[eWord][fWord] / normalizer
                            countsVogel[self.vogel_index(i,j,I,J)] += delta # do we only need to take the maximum probable likelihood?
                        else:
                            delta = transProbs[eWord][fWord] / normalizer
                        counts[eWord][fWord] += delta
                        countsEnglish[eWord] += delta                

            logLikelihood.append(logLike)
            print logLike

            # check for log-likelihood convergence
            if len(logLikelihood) > 1:
                difference = logLikelihood[-1] - logLikelihood[-2]
                if difference < threshold:
                    converged = True
                    break

            # Maximization - step
            print "M"
            for eKey in transProbs:
                for fKey in transProbs[eKey]:
                    # update translation probabilities
                    transProbs[eKey][fKey] = counts[eKey][fKey] / countsEnglish[eKey]
            if self.model == self.IBM2:
                # update Vogel-based alignment probabilities
                normalizer = sum(countsVogel.itervalues())
                probsVogel = {k: v / normalizer for k, v in countsVogel.iteritems()}
                
            end = time.time()
            print end-start

        return transProbs, probsVogel

    def get_alignments(pairs, transProbs, model="ibm1", vogelProbs=[]):
        """Get the predicted alignments on sentence pairs from a trained ibm model 1 or 2"""
        alignments = []
        if model == "ibm1":
            for k, pair in enumerate(pairs):
                alignments.append([])
                for fWord in pair[1]:
                    maxProb = 0.0
                    alignment = 0
                    for i, eWord in enumerate(pair[0]):
                        if eWord in transProbs:
                            if fWord in transProbs[eWord]:
                                alignProb = transProbs[eWord][fWord]
                        if alignProb > maxProb:
                            maxProb = alignProb
                            alignment = i
                    alignments[k].append(alignment)
        elif model == "ibm2":
            for k, pair in enumerate(pairs):
                alignments.append([])
                I = len(pair[0])
                J = len(pair[1])
                for j, fWord in enumerate(pair[1]):
                    maxProb = 0.0
                    alignment = 0
                    for i, eWord in enumerate(pair[0]):
                        if eWord in transProbs:
                            if fWord in transProbs[eWord]:
                                alignProb = transProbs[eWord][fWord] * vogelProbs[self.vogel_index(i, j, I, J)]
                        if alignProb > maxProb:
                            maxProb = alignProb
                            alignment = i
                    alignments[k].append(alignment)
        return alignments
