from random import random, seed, randrange, choice
import numpy as np
import logging
import os
from datetime import datetime 
import json


def createFolderPath(filePath):
	'''
	Makes sure that all the folders in the filePath exist
	'''
	outputdir = os.path.dirname(filePath)

	#Make sure output dir exists
	outputHier = os.path.normpath(outputdir)
	outputHierList = outputHier.split(os.sep)
	currentPath = ""
	for folder in outputHierList:
		currentPath = os.path.join(currentPath, folder)
		if not (os.path.exists(currentPath)):
			os.mkdir(currentPath)


def getLogger(name, console="WARNING", outputdir="LOGS", logFile=True, fileLevel="INFO"):
	'''
	Returns logger object
	'''

	#Make sure output dir exists
	outputHier = os.path.normpath(outputdir)
	outputHierList = outputHier.split(os.sep)
	currentPath = ""
	for folder in outputHierList:
		currentPath = os.path.join(currentPath, folder)
		if not (os.path.exists(currentPath)):
			os.mkdir(currentPath)

	#Instantiate logger
	logger = logging.getLogger(name)
	logger.setLevel(logging.DEBUG)

	# create file handler which logs even debug messages
	fh = None
	if (logFile):
		logPath = os.path.join(outputdir, "{}.log".format(name).replace(":", "_"))
		fh = logging.FileHandler(logPath, mode="w")
		fh.setLevel(logging.DEBUG)
		if (fileLevel=="CRITICAL"):
			fh.setLevel(logging.CRITICAL)
		if (fileLevel=="ERROR"):
			fh.setLevel(logging.ERROR)
		if (fileLevel=="WARNING"):
			fh.setLevel(logging.WARNING)
		if (fileLevel=="INFO"):
			fh.setLevel(logging.INFO)
		if (fileLevel=="DEBUG"):
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
	formatter = logging.Formatter('%(asctime)s.%(msecs)03d\t--%(levelname)s--\t%(name)s:\t%(message)s', datefmt='%m/%d/%Y %H:%M:%S')
	if (logFile):
		fh.setFormatter(formatter)
	ch.setFormatter(formatter)

	# add the handlers to the logger
	if (logFile):
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


def getTimeStamp(sanitize=True):
	date_time = datetime.now()
	timeStamp = date_time.strftime("%m/%d/%Y %H:%M:%S")
	if (sanitize):
		timeStamp = timeStamp.replace("/", "_").replace(":", "_").replace(" ", "__")

	return timeStamp


def dictToJsonFile(dictionary, filePath):
	jsonStr = json.dumps(dictionary, indent=4)
	createFolderPath(filePath)

	file = open(filePath, "w")
	file.write(jsonStr)
	file.close()

def truncateFloat(value, percision):
	truncatedFloat = float(int(value*pow(10, percision)))/pow(10, percision)
	return truncatedFloat


def loadItemDict(itemDir):
	allItemsDict = {}
	for fileName in os.listdir(itemDir):
		try:
			path = os.path.join("Items", fileName)
			if (os.path.isfile(path)):
				itemDictFile = open(path, "r")
				itemDict = json.load(itemDictFile)
				itemDictFile.close()

				allItemsDict[itemDict["id"]] = itemDict
			elif (os.path.isdir(path)):
				for subFileName in os.listdir(path):
					subPath = os.path.join(path, subFileName)
					if (os.path.isfile(subPath)):
						itemDictFile = open(subPath, "r")
						itemDict = json.load(itemDictFile)
						itemDictFile.close()

						allItemsDict[itemDict["id"]] = itemDict
		except:
			pass

	return allItemsDict