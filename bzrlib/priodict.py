# Priority dictionary using binary heaps
# David Eppstein, UC Irvine, 8 Mar 2002

# Implements a data structure that acts almost like a dictionary, with two modifications:
# (1) D.smallest() returns the value x minimizing D[x].  For this to work correctly,
#        all values D[x] stored in the dictionary must be comparable.
# (2) iterating "for x in D" finds and removes the items from D in sorted order.
#        Each item is not removed until the next item is requested, so D[x] will still
#        return a useful value until the next iteration of the for-loop.
# Each operation takes logarithmic amortized time.

from __future__ import generators

class priorityDictionary(dict):
	def __init__(self):
		'''Initialize priorityDictionary by creating binary heap of pairs (value,key).
Note that changing or removing a dict entry will not remove the old pair from the heap
until it is found by smallest() or until the heap is rebuilt.'''
		self.__heap = []
		dict.__init__(self)

	def smallest(self):
		'''Find smallest item after removing deleted items from front of heap.'''
		if len(self) == 0:
			raise IndexError, "smallest of empty priorityDictionary"
		heap = self.__heap
		while heap[0][1] not in self or self[heap[0][1]] != heap[0][0]:
			lastItem = heap.pop()
			insertionPoint = 0
			while 1:
				smallChild = 2*insertionPoint+1
				if smallChild+1 < len(heap) and heap[smallChild] > heap[smallChild+1] :
					smallChild += 1
				if smallChild >= len(heap) or lastItem <= heap[smallChild]:
					heap[insertionPoint] = lastItem
					break
				heap[insertionPoint] = heap[smallChild]
				insertionPoint = smallChild
		return heap[0][1]
	
	def __iter__(self):
		'''Create destructive sorted iterator of priorityDictionary.'''
		def iterfn():
			while len(self) > 0:
				x = self.smallest()
				yield x
				del self[x]
		return iterfn()
	
	def __setitem__(self,key,val):
		'''Change value stored in dictionary and add corresponding pair to heap.
Rebuilds the heap if the number of deleted items gets large, to avoid memory leakage.'''
		dict.__setitem__(self,key,val)
		heap = self.__heap
		if len(heap) > 2 * len(self):
			self.__heap = [(v,k) for k,v in self.iteritems()]
			self.__heap.sort()  # builtin sort probably faster than O(n)-time heapify
		else:
			newPair = (val,key)
			insertionPoint = len(heap)
			heap.append(None)
			while insertionPoint > 0 and newPair < heap[(insertionPoint-1)//2]:
				heap[insertionPoint] = heap[(insertionPoint-1)//2]
				insertionPoint = (insertionPoint-1)//2
			heap[insertionPoint] = newPair
	
	def setdefault(self,key,val):
		'''Reimplement setdefault to pass through our customized __setitem__.'''
		if key not in self:
			self[key] = val
		return self[key]
