import multiprocessing
import threading
import hashlib
import logging
import time


class NetworkPacket:
	def __init__(self, senderId, destinationId, msgType, payload=None, transactionId=None):
		self.msgType = msgType
		self.payload = payload
		self.senderId = senderId
		self.destinationId = destinationId
		self.transactionId = transactionId

		hashStr = "{}{}{}{}{}{}".format(msgType, payload, senderId, destinationId, transactionId, time.time())
		self.hash = hashlib.sha256(hashStr.encode('utf-8')).hexdigest()[:8 ]

	def __str__(self):
		return "({}, {}, {}, {})".format(self.msgType, self.destinationId, self.transactionId, self.hash)

class TransactionNetwork:
	def __init__(self):
		self.logger = logging.getLogger("{}".format(__name__))
		self.lockTimeout = 5

		self.agentConnections = {}
		self.agentConnectionsLock = threading.Lock()

	def addConnection(self, agentId, networkPipe):
		self.agentConnections[agentId] = networkPipe

	def startMonitors(self):
		for agentId in self.agentConnections:
			monitorThread = threading.Thread(target=self.monitorLink, args=(agentId,))
			monitorThread.start()

	def monitorLink(self, agentId):
		agentLink = self.agentConnections[agentId]
		self.logger.info("Monitoring {} link {}".format(agentId, agentLink))
		while True:
			incommingPacket = agentLink.recv()
			self.logger.info("INBOUND {}".format(incommingPacket))
			destinationId = incommingPacket.destinationId

			if (incommingPacket.msgType == "KILL_PIPE_NETWORK"):
					#We've received a kill command for this pipe. Remove destPipe from connections, then kill this monitor thread
					self.logger.info("Killing pipe {} {}".format(agentId, agentLink))
					self.logger.debug("Lock \"agentConnectionsLock\" requested")
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire(timeout=self.lockTimeout)
					if (acquired_agentConnectionsLock):
						self.logger.debug("Lock \"agentConnectionsLock\" acquired")
						del self.agentConnections[destinationId]
						self.logger.debug("Lock \"agentConnectionsLock\" release")
						self.agentConnectionsLock.release()
						break
					else:
						self.logger.error("Lock \"agentConnectionsLock\" acquisition timeout")
						break

			elif (destinationId in self.agentConnections):
				outboundLink = self.agentConnections[destinationId]
				self.logger.info("OUTBOUND {}".format(incommingPacket))
				outboundLink.send(incommingPacket)

			else:
				errorMsg = "Destination \"{}\" not connected to network".format(destinationId)
				responsePacket = NetworkPacket(senderId="TransactionNetwork", destinationId=incommingPacket.senderId, msgType="ERROR", payload=errorMsg, transactionId=incommingPacket.transactionId)
				agentLink.send(responsePacket)


def childWait(conn):
	while True:
		incommingPacket = conn.recv()
		if (incommingPacket == "END"):
			break
		print(incommingPacket.payload)


if __name__ == '__main__':
	parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
	
	childProc = multiprocessing.Process(target=childWait, args=(child_conn,))
	childProc.start()

	#parent_conn.send("Hello")
	#parent_conn.send("World")
	#parent_conn.send("!")
	packet = NetworkPacket("telegram", {"message": "good tidings"})
	parent_conn.send(packet)
	parent_conn.send("END")
	parent_conn.send("Don't see me")

	childProc.join()