from random import random, seed, randrange, choice
import numpy as np
import logging
import os


def getLogger(name, console="WARNING"):
	'''
	Returns logger object
	'''
	logger = logging.getLogger(name)
	logger.setLevel(logging.DEBUG)

	# create file handler which logs even debug messages
	logPath = os.path.join("LOGS", "{}.log".format(name).replace(":", "_"))
	fh = logging.FileHandler(logPath, mode="w")
	fh.setLevel(logging.DEBUG)

	# create console handler with a higher log level
	ch = logging.StreamHandler()
	ch.setLevel(logging.INFO)
	if (console=="CRITICAL"):
		ch.setLevel(logging.CRITICAL)
	if (console=="ERROR"):
		ch.setLevel(logging.ERROR)
	if (console=="WARNING"):
		ch.setLevel(logging.WARNING)
	if (console=="INFO"):
		ch.setLevel(logging.INFO)
	if (console=="DEBUG"):
		ch.setLevel(logging.DEBUG)

	# create formatter and add it to the handlers
	formatter = logging.Formatter('%(asctime)s.%(msecs)03d\t%(levelname)s:\t%(name)s:\t%(message)s', datefmt='%m/%d/%Y %H:%M:%S')
	fh.setFormatter(formatter)
	ch.setFormatter(formatter)

	# add the handlers to the logger
	logger.addHandler(fh)
	logger.addHandler(ch)

	return logger


def getNormalSample(mean, std, onlyPositive=True):
	'''
	Returns a single sample from a normal distribution
	'''
	sample = np.random.normal(mean, std, 1)[0]
	if (onlyPositive):
		while (sample < 0):
			sample = np.random.normal(mean, std, 1)[0]
	return sample

