import hashlib
import time


class InfoRequest:
	def __init__(self, requesterId, agentId, infoKey):
		self.requesterId = requesterId
		self.agentId = agentId
		self.infoKey = infoKey
		self.info = None

		stringTemp = "{}{}{}".format(requesterId, agentId, infoKey)
		self.hash = hashlib.sha256(stringTemp.encode('utf-8')).hexdigest()[:8 ]
		self.reqString = "InfoReq_{}(requesterId={}, agentId={}, infoKey={})".format(self.hash, requesterId, agentId, infoKey)

	def __str__(self):
		return self.reqString


class ItemListing:
	def __init__(self, sellerId, itemId, unitPrice, maxQuantity):
		self.sellerId = sellerId
		self.itemId = itemId
		self.unitPrice = unitPrice
		self.maxQuantity = maxQuantity

		tempListingStr = "ItemListing(seller={}, item={}, price={}, max={})".format(sellerId, itemId, unitPrice, maxQuantity)
		self.hash = hashlib.sha256(tempListingStr.encode('utf-8')).hexdigest()[:8 ]
		self.listingStr = "ItemListing_{}(seller={}, item={}, price={}, max={})".format(self.hash, sellerId, itemId, unitPrice, maxQuantity)

	def __str__(self):
		return self.listingStr


class ItemContainer:
	def __init__(self, itemId, itemQuantity):
		self.id = itemId
		self.quantity = itemQuantity

	def __repr__(self):
		return str(self)

	def __str__(self):
		return "ItemContainer(ID={}, Quant={})".format(self.id, self.quantity)

	def __add__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			newEntry = ItemContainer(self.id, self.quantity+other.quantity)
			return newEntry
		elif ((typeOther == int) or (typeOther == float)):
			newEntry = ItemContainer(self.id, self.quantity+other)
			return newEntry
		else:
			raise ValueError("Cannot add {} and {}".format(typeOther, type(self)))

	def __sub__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			newEntry = ItemContainer(self.id, self.quantity-other.quantity)
			return newEntry
		elif ((typeOther == int) or (typeOther == float)):
			newEntry = ItemContainer(self.id, self.quantity-other)
			return newEntry
		else:
			raise ValueError("Cannot subtract {} and {}".format(typeOther, type(self)))

	def __iadd__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			self.quantity += other.quantity
			return self
		elif ((typeOther == int) or (typeOther == float)):
			self.quantity += other
			return self
		else:
			raise ValueError("Cannot add {} and {}".format(typeOther, type(self)))

	def __isub__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot subtract inventory entries of different items {} and {}".format(self.id, otherId))

			self.quantity -= other.quantity
			return self
		elif ((typeOther == int) or (typeOther == float)):
			self.quantity -= other
			return self
		else:
			raise ValueError("Cannot subtract {} and {}".format(typeOther, type(self)))


class LaborListing:
	def __init__(self, employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName="JobListing"):
		self.employerId = employerId
		self.ticksPerStep = ticksPerStep
		self.wagePerTick = wagePerTick
		self.minSkillLevel = minSkillLevel
		self.contractLength = contractLength
		self.listingName = listingName

		tempListingStr = "LaborListing(employerId={}, ticksPerStep={}, wagePerTick={}, minSkillLevel={}, contractLength={}, listingName={})".format(employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName)
		self.hash = hashlib.sha256(tempListingStr.encode('utf-8')).hexdigest()[:8 ]
		self.listingStr = "LaborListing_{}(employerId={}, ticksPerStep={}, wagePerTick={}, minSkillLevel={}, contractLength={}, listingName={})".format(self.hash, employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName)

	def generateLaborContract(self, workerId, workerSkillLevel, startStep):
		return LaborContract(self.employerId, workerId, self.ticksPerStep, self.wagePerTick, workerSkillLevel, self.contractLength, startStep, startStep+self.contractLength-1, self.hash, "EmploymentContract_{}_{}_{}".format(self.employerId, workerId, startStep))

	def __str__(self):
		return self.listingStr


class LaborContract:
	def __init__(self, employerId, workerId, ticksPerStep, wagePerTick, workerSkillLevel, contractLength, startStep, endStep, listingHash, contractName="EmploymentContract"):
		self.employerId = employerId
		self.workerId = workerId
		self.ticksPerStep = ticksPerStep
		self.wagePerTick = wagePerTick
		self.workerSkillLevel = workerSkillLevel
		self.contractLength = contractLength
		self.startStep = startStep
		self.endStep = endStep
		self.contractName = contractName

		tempContractStr = "LaborContract(employerId={}, workerId={}, ticksPerStep={}, wagePerTick={}, workerSkillLevel={}, contractLength={}, startStep={}, endStep={}, contractName={})".format(employerId, workerId, ticksPerStep, wagePerTick, workerSkillLevel, contractLength, startStep, endStep, contractName)
		self.hash = hashlib.sha256(tempContractStr.encode('utf-8')).hexdigest()[:8 ]
		self.contractStr = "LaborContract_{}(employerId={}, workerId={}, ticksPerStep={}, wagePerTick={}, workerSkillLevel={}, contractLength={}, startStep={}, endStep={}, contractName={})".format(self.hash, employerId, workerId, ticksPerStep, wagePerTick, workerSkillLevel, contractLength, startStep, endStep, contractName)

	def __str__(self):
		return self.contractStr


class TradeRequest:
	def __init__(self, sellerId, buyerId, currencyAmount, itemPackage):
		self.sellerId = sellerId
		self.buyerId = buyerId
		self.currencyAmount = currencyAmount
		self.itemPackage = itemPackage

		reqString = "TradeReq(seller={}, buyerId={}, currency={}, item={})_{}".format(sellerId, buyerId, currencyAmount, itemPackage, time.time())

		self.hash = hashlib.sha256(reqString.encode('utf-8')).hexdigest()[:8 ]
		self.reqId = "TradeReq_{}(seller={}, buyerId={}, currency={}, item={})".format(self.hash, sellerId, buyerId, currencyAmount, itemPackage)

	def __str__(self):
		return self.reqId


class LandListing:
	def __init__(self, sellerId, hectares, allocation, pricePerHectare):
		self.sellerId = sellerId
		self.hectares = hectares
		self.allocation = allocation
		self.pricePerHectare = pricePerHectare

		tempListingStr = "LandListing(seller={}, hectares={}, pricePerHectare={}, allocation={})".format(sellerId, hectares, pricePerHectare, allocation)
		self.hash = hashlib.sha256(tempListingStr.encode('utf-8')).hexdigest()[:8 ]
		self.listingStr = "LandListing_{}(seller={}, hectares={}, pricePerHectare={}, allocation={})".format(self.hash, sellerId, hectares, pricePerHectare, allocation)

	def __str__(self):
		return self.listingStr