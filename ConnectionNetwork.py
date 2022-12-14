import multiprocessing
import threading
import hashlib
import time

import utils


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
		return "({}, {}, {}, {})".format(self.msgType, self.destinationId, self.transactionId, self.hash)

class ConnectionNetwork:
	def __init__(self, logFile=True):
		self.logger = utils.getLogger("{}".format(__name__), logFile=logFile)
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
			self.logger.info("INBOUND {} {}".format(agentId, incommingPacket))
			destinationId = incommingPacket.destinationId

			if (incommingPacket.msgType == "KILL_PIPE_NETWORK"):
					#We've received a kill command for this pipe. Remove destPipe from connections, then kill this monitor thread
					self.logger.info("Killing pipe {} {}".format(agentId, agentLink))
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire(timeout=self.lockTimeout)  #<== acquire agentConnectionsLock
					if (acquired_agentConnectionsLock):
						del self.agentConnections[destinationId]
						self.agentConnectionsLock.release()  #<== release agentConnectionsLock
						break
					else:
						self.logger.error("monitorLink() Lock \"agentConnectionsLock\" acquisition timeout")
						break

			elif ("_BROADCAST" in incommingPacket.msgType):
					#We've received a broadcast message. Foward to all pipes
					for pipeId in self.agentConnections:
						self.agentConnections[pipeId].send(incommingPacket)

			elif (destinationId in self.agentConnections):
				#Foward packet to destination
				outboundLink = self.agentConnections[destinationId]
				self.logger.info("OUTBOUND {} {}".format(destinationId, incommingPacket))
				outboundLink.send(incommingPacket)

			else:
				#Invalid packet destination
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