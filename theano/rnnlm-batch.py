from __future__ import division
import theano.tensor as T
import theano
import numpy as np
import sys, time
import random
import cProfile
from itertools import chain

from nn.layers.recurrent import LSTM
from nn.layers.embeddings import Embedding
from nn.optimizers import Adam, SGD
from nn.initializations import uniform

from collections import Counter, defaultdict
from itertools import count


EMBEDDING_DIM = 64
LSTM_HIDDEN_DIM = 128
MB_SIZE = 10


train_file = 'data/text/train.txt'
test_file = 'data/text/dev.txt'

w2i = defaultdict(count(0).next)


def read(fname):
    """
    Read a file where each line is of the form "word1 word2 ..."
    Yields lists of the form [word1, word2, ...]
    """
    with file(fname) as fh:
        for line in fh:
            sent = [w2i[x] for x in line.strip().split()]
            sent.append(w2i["<s>"])
            yield sent

mask = w2i['<MASK>']
assert mask == 0

train = list(read(train_file))
vocab_size = len(w2i)
test = list(read(test_file))
S = w2i['<s>']


def pad(seq):
    """
    pad a mini-batch input with ending zeros
    """
    batch_size = len(seq)
    max_len = max(len(seq[i]) for i in xrange(batch_size))
    padded_seq = np.zeros((batch_size, max_len), dtype='int32')
    for i in xrange(batch_size):
        padded_seq[i, :len(seq[i])] = seq[i]

    return padded_seq


def build_graph():
    # print 'build graph..'
    # Lookup parameters for word embeddings
    embedding_table = Embedding(vocab_size, EMBEDDING_DIM)

    lstm = LSTM(EMBEDDING_DIM, LSTM_HIDDEN_DIM, inner_init="identity", return_sequences=True)

    # Softmax weights/biases on top of LSTM outputs
    W_sm = uniform((LSTM_HIDDEN_DIM, vocab_size), scale=.5, name='W_sm')
    b_sm = uniform(vocab_size, scale=.5, name='b_sm')

    # (batch_size, sentence_length)
    x = T.imatrix(name='sentence')

    # (batch_size, sentence_length, embedding_dim)
    sent_embed, sent_mask = embedding_table(x, mask_zero=True)

    lstm_input = T.set_subtensor(T.zeros_like(sent_embed)[:, 1:, :], sent_embed[:, :-1, :])
    lstm_input = T.set_subtensor(lstm_input[:, 0, :], sent_embed[:, -1, :])

    # (batch_size, sentence_length, output_dim)
    lstm_output = lstm(lstm_input)

    # (batch_size, sentence_length, vocab_size)
    logits = T.dot(lstm_output, W_sm) + b_sm
    logits = T.nnet.softmax(logits.reshape((logits.shape[0] * logits.shape[1], vocab_size))).reshape(logits.shape)

    loss = T.log(logits).reshape((-1, logits.shape[-1]))
    # (batch_size * sentence_length)
    loss = loss[T.arange(loss.shape[0]), x.flatten()]
    # (batch_size, sentence_length)
    loss = - loss.reshape((x.shape[0], x.shape[1])) * sent_mask
    # loss = loss.sum(axis=-1) / sent_mask.sum(axis=-1)
    # loss = -T.mean(loss)

    # loss is the sum of nll over all words over all examples in the mini-batch
    loss = loss.sum()

    params = embedding_table.params + lstm.params + [W_sm, b_sm]
    updates = Adam(lr=0.001).get_updates(params, loss)
    # updates = SGD(lr=0.01).get_updates(params, loss)
    train_loss_func = theano.function([x], loss, updates=updates)
    test_loss_func = theano.function([x], loss)

    return train_loss_func, test_loss_func


def train_model():
    train_loss_func, test_loss_func = build_graph()

    i = all_time = all_tagged = this_words = this_loss = 0

    # Sort training sentences in descending order and count minibatches
    train.sort(key=lambda x: -len(x))
    test.sort(key=lambda x: -len(x))
    train_order = [x * MB_SIZE for x in range(int((len(train) - 1) / MB_SIZE + 1))]
    test_order = [x * MB_SIZE for x in range(int((len(test) - 1) / MB_SIZE + 1))]

    # Perform training
    start = time.time()
    for ITER in xrange(10):
        random.shuffle(train_order)
        for sid in train_order:
            i += 1
            if i % (500 / MB_SIZE) == 0:
                print this_loss / this_words
                all_tagged += this_words
                this_loss = this_words = 0
            if i % (10000 / MB_SIZE) == 0:
                all_time += time.time() - start
                dev_loss = dev_words = 0
                for test_sid in test_order:
                    batch_sents = test[test_sid:test_sid + MB_SIZE]
                    batch_sents_x = pad(batch_sents)

                    batch_loss = test_loss_func(batch_sents_x)
                    dev_loss += batch_loss

                    mb_words = sum(len(s) for s in batch_sents)
                    dev_words += mb_words

                print ("nll=%.4f, ppl=%.4f, words=%r, time=%.4f, word_per_sec=%.4f" % (
                    dev_loss / dev_words, np.exp(dev_loss / dev_words), dev_words, all_time, all_tagged / all_time))
                if all_time > 3600:
                    sys.exit(0)
                start = time.time()

            # train on the minibatch

            batch_sents = train[sid:sid + MB_SIZE]
            batch_sents_x = pad(batch_sents)

            batch_loss = train_loss_func(batch_sents_x)
            this_loss += batch_loss
            print("loss @ %r: %r" % (i, this_loss))
            mb_words = sum(len(s) for s in batch_sents)
            this_words += mb_words

        print "epoch %r finished" % ITER


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print 'usage: %s BATCH_SIZE (set to 1 for non-minibatch case)' % sys.argv[0]
        sys.exit(-1)

    MB_SIZE = int(sys.argv[1])
    print >>sys.stderr, 'batch size = %d' % MB_SIZE

    train_model()

    # cProfile.run('train_model()', sort=2)
