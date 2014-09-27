from collections import deque
try:
	from collections.abc import Sequence # 3.3+
except ImportError:
	from collections import Sequence
import itertools


DEBUG = True
def debug(*args, **kwargs):
	if DEBUG:
		print(*(('DEBUG:',) + args), **kwargs)


def _validate_slice_component(value):
	if value is None:
		return None
	try:
		value = value.__index__() # also works for ints
		if not isinstance(value, int):
			raise TypeError(
				'__index__ returned non-int (type {})'.format(type(value))
			)
		return value
	except AttributeError:
		raise TypeError(
			'slice indices must be integers or None or have an __index__ method'
		)


def validate_slice(s):
	"""Ensure that components of a slice are either None or integers,
	and that only the stop can be None (replacing this would require
	knowing the length of the sequence). Return the values as a tuple."""
	start, stop, step = map(
		_validate_slice_component,
		(s.start, s.stop, s.step)
	)
	if step is None:
		step = 1
	if step == 0:
		raise ValueError('slice step cannot be zero')
	if start is None:
		start = 0 if step > 0 else -1
	return start, stop, step


class BufferedImmutableIterable(Sequence):
	"""A class that remembers elements from iterating over an iterable
	and provides a read-only, indexable (tuple-like) interface to them."""

	def __init__(self, iterable, maxlen=None):
		# TODO: Different buffer types and slice types.
		# TODO: If the iterable is already a sequence, use it directly.
		self._iterator = iter(iterable)
		self._buffer = deque(maxlen=maxlen)
		# Total number of elements read from the iterable.
		# if maxlen is None, will equal the len of the buffer.
		self._read = 0
		self._maxlen = maxlen


	def _read_one(self):
		# TODO: this will also happen when the supplied iterable
		# is a sequence and we're using it directly.
		if self._iterator is None:
			return False
		debug("reading")
		try:
			value = next(self._iterator)
		except StopIteration:
			debug("failed")
			# Avoid the effort next time.
			self._iterator = None
			return False
		else:
			debug("read:", value)
			self._buffer.append(value)
			self._read += 1
			return True


	def _len_at_least(self, amount):
		# Determine whether the length of the iterable is
		# *at least* amount, by trying to read to that point.
		while self._read < amount:
			if not self._read_one():
				return False
		return True


	def _len_at_most(self, amount):
		# Determine whether the length of the iterable is
		# *at most* amount, by trying to read past that point.
		while self._read <= amount:
			if not self._read_one():
				return True
		return False


	def _get_item(self, index):
		if index < 0:
			if self._maxlen is not None and -index > self._maxlen:
				raise IndexError('index out of range')
			# Otherwise, we can only tell if the index is valid
			# by reading everything anyway, so do it right away.
			index += len(self)
		if not self._len_at_least(index + 1):
			raise IndexError('index out of range')
		# The negative indexing ensures this will work when maxlen is set.
		return self._buffer[index - self._read]


	def _islice(self, s):
		current, stop, step = validate_slice(s)

		# Do trimming if the start index is "before" the valid indices.
		# When iterating backwards, this happens when the start index is
		# positive and that it's past the end of the data.
		if step < 0 and current >= 0 and not self._len_at_least(current + 1):
			debug("correcting positive index")
			# If we get here, we've read everything, so len() is ok.
			limit = len(self) - 1
			# Since step is negative, this does the right thing with the remainder.
			current -= (current - limit) // step * step
			debug("new start:", current)

		# When iterating forwards, this happens when the start index is
		# negative and that it's before the beginning of the data.
		if step > 0 and current < 0 and not self._len_at_least(-current):
			debug("correcting negative index")
			# If we get here, we've read everything, so len() is ok.
			limit = -len(self)
			# Since (current - limit) is negative but step is positive,
			# this does the right thing with the remainder.
			current -= (current - limit) // step * step
			debug("new start:", current)

		start_negative = current < 0
		def valid_index():
			# Determine whether we've passed the limit set by `stop`.
			# Ensure we don't read more than necessary, even if `current == -1`,
			# since we might not actually do any indexing.
			if (current < 0) != start_negative:
				# changed signs during the iteration: we're done.
				return False
			if stop is None:
				return self._len_at_least(-current if current < 0 else current + 1)
			# Iff the index is valid, `low` is an index "before" `high`.
			low, high = (current, stop) if step > 0 else (stop, current)
			if (high < 0) == (low < 0):
				# Same sign, compare directly.
				return low < high
			if high < 0: # low >= 0
				return self._len_at_least(low - high + 1)
			# high >= 0, low < 0
			return self._len_at_most(high - low - 1)

		# Finally time to loop.
		while valid_index():
			debug("GET", current, stop)
			yield self[current]
			current += step


	def __getitem__(self, index):
		if isinstance(index, int):
			return self._get_item(index)
		elif isinstance(index, slice):
			return tuple(self._islice(index))
		else:
			raise TypeError('indices must be integers, not {}'.format(type(index)))


	def __len__(self):
		# No way around it: we need to read everything.
		while self._read_one(): pass
		return self._read


	def islice(self, *args):
		"""Analogous to itertools.islice, except there is also
		support for negative start/stop/step values using the buffer.

		Note that this can raise IndexError when maxlen is not None, if
		a corresponding slice of the entire 'sequence' would include
		elements that are already out of the buffer.

		In general, this function will read ahead as little as necessary
		at any given point in order to find out if the 'next' index is
		valid. It is advised not to write 'clever' code relying on this
		behaviour.
		"""
		return self._islice(slice(*args))
