import hashlib
import time


class ItemListing:
	def __init__(self, sellerId, itemId, unitPrice, maxQuantity):
		self.sellerId = sellerId
		self.itemId = itemId
		self.unitPrice = unitPrice
		self.maxQuantity = maxQuantity

		self.listingStr = "ItemListing(seller={}, item={}, price={}, max={})".format(sellerId, itemId, unitPrice, maxQuantity)
		self.hash = hashlib.sha256(self.listingStr.encode('utf-8')).hexdigest()[:8 ]

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


class TradeRequest:
	def __init__(self, sellerId, buyerId, currencyAmount, itemPackage):
		self.sellerId = sellerId
		self.buyerId = buyerId
		self.currencyAmount = currencyAmount
		self.itemPackage = itemPackage

		reqString = "TradeReq(seller={}, buyerId={}, currency={}, item={})_{}".format(sellerId, buyerId, currencyAmount, itemPackage, time.time())

		self.hash = hashlib.sha256(reqString.encode('utf-8')).hexdigest()[:8 ]
		self.reqId = "TradeReq(seller={}, buyerId={}, currency={}, item={})_{}".format(sellerId, buyerId, currencyAmount, itemPackage, self.hash)

	def __str__(self):
		return self.reqId

