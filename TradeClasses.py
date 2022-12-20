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

		tempStr = "{}_{}".format(itemId, itemQuantity)
		self.hash = hashlib.sha256(tempStr.encode('utf-8')).hexdigest()[:8 ]
		self.string = "ItemContainer_{}(ID={}, Quant={})".format(self.hash, self.id, self.quantity)


	def __repr__(self):
		return str(self)

	def __str__(self):
		return self.string

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
	def __init__(self, employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName="Employee"):
		self.employerId = employerId
		self.ticksPerStep = ticksPerStep
		self.wagePerTick = wagePerTick
		self.minSkillLevel = minSkillLevel
		self.contractLength = contractLength
		self.listingName = listingName

		tempListingStr = "LaborListing(employerId={}, ticksPerStep={}, wagePerTick={}, minSkillLevel={}, contractLength={}, listingName={})".format(employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName)
		self.hash = hashlib.sha256(tempListingStr.encode('utf-8')).hexdigest()[:8 ]
		self.listingStr = "LaborListing_{}(employerId={}, ticksPerStep={}, wagePerTick={}, minSkillLevel={}, contractLength={}, listingName={})".format(self.hash, employerId, ticksPerStep, wagePerTick, minSkillLevel, contractLength, listingName)

	def __str__(self):
		return self.listingStr


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

