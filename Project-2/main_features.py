from training.features import *
from gensim.models import Word2Vec
import training.model as model
import time

"""script for generating features from forests"""
EMBED = False
BIGRAM = False
embedpath = "chEmbeddings100"
bipath = "biProbs"
bijoinpath = "jointProbs"

if EMBED:
    print('embed')
    chEmbeddings = get_word_embeddings("datamap/chinese.zh-en", iterations=500, name="chEmbeddings100")
    enEmbeddings = get_word_embeddings("datamap/english.zh-en", iterations=500, name="enEmbeddings100")

    print(enEmbeddings.wv.similarity("man", "woman"))
    print(enEmbeddings.wv.similarity("big", "large"))
    print(enEmbeddings.most_similar(positive=["man"]))
    print(enEmbeddings.most_similar(positive=["woman"]))
    print(enEmbeddings.most_similar(positive=["fish"]))
    print(enEmbeddings.most_similar(positive=["big"]))
    print(enEmbeddings.most_similar(positive=["the"]))
    print(enEmbeddings.most_similar(positive=["problem"]))
else:
    # if globals.USE_COMPLEX_FEATURES:
    #     chEmbeddings = Word2Vec.load(embedpath)
    #     chEmbeddings = chEmbeddings.wv
    # else:
    chEmbeddings = 0

if BIGRAM:
    print("bigram")
    bi_joint_probs, bi_probs = get_bigram_probabilities("datamap/chinese.zh-en")
else:
    if globals.USE_COMPLEX_FEATURES:
        bi_joint_probs = pickle.load(open(bijoinpath, 'rb'))
        bi_probs = pickle.load(open(bipath, 'rb'))
    else:
        bi_joint_probs = 0
        bi_probs = 0


# for key in bi_probs:
#     density = 0.0
#     for key2 in bi_probs[key]:
#         if bi_probs[key][key2] > 0.2:
#             print(key, key2, bi_probs[key][key2])

# TODO extract the features

source_lexicon, target_lexicon = Data.generate_IBM_lexicons()
# itgs = Data.read_forests()

forests = [globals.ITG_SUBSET_1_FILE_PATH, globals.ITG_SUBSET_2_FILE_PATH, globals.ITG_SUBSET_3_FILE_PATH]
corpus = [globals.TRAINING_SUBSET_1_FILE_PATH, globals.TRAINING_SUBSET_2_FILE_PATH, globals.TRAINING_SUBSET_3_FILE_PATH]

number_of_instances = 0

for subset in forests:
    for i in range(6):
        subset_file_path = subset[:-5] + str(i + 1) + subset[-5:]
        itgs = Data.read_forests(subset_file_path)
        number_of_instances += len(itgs)


forests_file = open("datamap/training_forests.itgs", "wb")
features_file = open("datamap/training_features.ftrs", "wb")

start_time = time.clock()
number_of_instances_featurized_so_far = 0

for i, forest_subset in enumerate(forests):
    number_of_instances_featurized_so_far = generate_features_all(source_lexicon, target_lexicon, forest_subset, corpus[i],
                                                                  forests_file, features_file, number_of_instances,
                                                                  number_of_instances_featurized_so_far, start_time,
                                                                  bi_probs, bi_joint_probs, chEmbeddings)


forests_file.close()
features_file.close()
