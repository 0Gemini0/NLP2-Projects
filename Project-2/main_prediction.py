from training import MLE, prediction
import pickle
import globals
import libitg

# generate some weights for a shitload of sentences, with y = 0.75 and l = 0.75 (lower bound on optimal setting)
weight, avg_loss, val_loss, t, tstar = MLE.stochastic_gradient_descent(25, 0.75, 1.0, 1, 40, 1000, True, 0.75)
print(weight[-1])

# store some stuff ya know
pickle.dump(weight, open("1000_sen_y_0.75_l_0.75_weights", "wb"))
pickle.dump(avg_loss, open("1000_sen_y_0.75_l_0.75_avg_loss", "wb"))
pickle.dump(val_loss, open("1000_sen_y_0.75_l_0.75_val_loss", "wb"))

# print some more stuff
print(val_loss[-1])
print(t)
print(tstar)

# get the forest

# get the correct filenames for loading from globals
forests_file = globals.ITG_FILE_PATH
features_file = globals.FEATURES_FILE_PATH

# start reading forest files
forests = open(forests_file, "rb")
features = open(features_file, "rb")

# forest and feature of first training thing
forest = pickle.load(forests)
feature = pickle.load(features)
forest_check = forest[2]
forest = forest[1]
feature = feature[0]

# get tsort and weights
edge_weights = {}
for edge in forest:
    # weight of each edge in the forest based on its features and the current wmap
    edge_weights[edge] = MLE.weight_function(edge, feature[edge], weight[-1])

# compute tsort
parents = MLE.get_parents_dict(forest)
tsort = MLE.top_sort(forest, parents)

# try me some viterbi
inside1 = MLE.inside_algorithm(forest, tsort, edge_weights)
inside = MLE.inside_viterbi(forest, tsort, edge_weights)
print(inside1)
print(inside)
viterbi = prediction.viterbi_decoding(forest, tsort, edge_weights, inside)

print(libitg.language_of_fsa(libitg.forest_to_fsa(forest_check, libitg.Nonterminal("D_i(x,y)"))))
# print(libitg.language_of_fsa(libitg.forest_to_fsa(forest, libitg.Nonterminal("D_i(x)"))))
# cfg = libitg.earley(forest, libitg.forest_to_fsa(forest_check, libitg.Nonterminal("D_i(x,y)")), libitg.Nonterminal("D_i(x)"),
#                     libitg.Nonterminal("D"))
# print(cfg)
print(viterbi)






