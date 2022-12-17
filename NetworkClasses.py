import hashlib
import time


class NetworkPacket:
	def __init__(self, senderId, msgType, destinationId=None, payload=None, transactionId=None):
		self.msgType = msgType
		self.payload = payload
		self.senderId = senderId
		self.destinationId = destinationId
		self.transactionId = transactionId

		hashStr = "{}{}{}{}{}{}".format(msgType, payload, senderId, destinationId, transactionId, time.time())
		self.hash = hashlib.sha256(hashStr.encode('utf-8')).hexdigest()[:8 ]

	def __str__(self):
		return "({}_{}, {}, {}, {})".format(self.msgType, self.hash, self.senderId, self.destinationId, self.transactionId)

class Link:
	def __init__(self, sendPipe, recvPipe):
		self.sendPipe = sendPipe
		self.recvPipe = recvPipe