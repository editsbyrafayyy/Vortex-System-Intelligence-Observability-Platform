import os
from typing import Iterator

# Default: 120 snapshots × ~5s polling ≈ 10 minutes of in-memory history.
_DEFAULT_CAPACITY = int(os.getenv("RING_BUFFER_SIZE", 120))

class RingBuffer: # ring buffer
    """
    A fixed-capacity circular buffer for metric snapshots. Slots are pre-allocated as a list of None values so memory usage is
    constant from creation — the buffer never grows or shrinks.

    Complexity:
      push()    — O(1)  : write one slot, advance one pointer
      to_list() — O(n)  : read all n slots in chronological order
      __len__   — O(1)  : counter maintained on every push
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None: # constructor
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}") 

        self._capacity: int = capacity 
        ''' We are preallocating slots to ensure that the buffer itself doesn't start serving as noise in the DB,
        while this will have very minor performance difference, we just want to ensure that the size of the buffer is knows
        before the program runs (fixing the memory footprint the buffer has)'''
        self._slots: list[dict | None] = [None] * capacity # the slots store the pointers to where the snapshots are stored (hence we have 120 pointer sized slots)
        self._head: int = 0 # Points to the slot where the *next* push will write.
        self._size: int = 0 # Tracks how many slots are occupied (caps at capacity).

    def push(self, snapshot: dict) -> None: # main operation, pushing the ptrs for the dictionaries into the ring buffer
        """
        Write a snapshot into the next slot.
        If the buffer is full, the oldest snapshot is silently overwritten.
        """
        self._slots[self._head] = snapshot 
        ''' important note: python always stores ptrs of objects, never the objects itself, so here
        we store the ptr for the snapshot dict '''

        self._head = (self._head + 1) % self._capacity # move to the next slot, we use the % capacity to achieve the circular nature 

        if self._size < self._capacity: # Only increment size until we've filled every slot once.
            self._size += 1

    def list_output(self) -> list[dict]:
        if self.size == 0:
            return []

        if self.size < self._capacity:
            return list(self._slots[: self._size]) # return buffer content from 0 to where the head - 1 is (size = head here)

        return self._slots[self._head :] + self._slots[: self._head] 
        ''' this last case deals with the circular part of the buffer, the first part [self._head :] means grab everything old till the end
        of right end of queue, and the [: self._head] parts refers to the newly added elements
        example: [Data4, Data5, Data1, Data2, Data3], here ._head is on Data1 so the first part means Data1-3 then the remaining Data4 and Data5'''

    def latest(self) -> dict | None:
        """Return the most recently pushed snapshot, or None if empty"""
        if self._size == 0:
            return None
        
        last_index = (self._head - 1) % self._capacity # The slot just before head holds the most recent write
        return self._slots[last_index]

    def is_full(self) -> bool:
        return self._size == self._capacity 
        """True when the buffer has reached capacity and will start overwriting."""

    def clear(self) -> None:
        """Reset the buffer to its empty state without reallocating slots."""
        self._slots = [None] * self._capacity
        self._head = 0
        self._size = 0