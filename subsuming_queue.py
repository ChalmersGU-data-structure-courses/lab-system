import logging
import threading


logger = logging.getLogger(__name__)

def rebuild_queue(queue_it, item):
    '''
    Rebuild a subsuming queue while adding an item to it.
    Takes an iterator for the current queue and the item to add.
    Returns an iterator for the new queue.
    '''
    for entry in queue_it:
        # Does entry have priority over us?
        # Is so, leave queue as is.
        if item >= entry:
            yield entry
            yield from queue_it
            return

        # Do we have strict priority?
        # If so, yield item and remove further entries
        # over which we have priority from queue.
        if item <= entry:
            yield item
            for entry in queue_it:
                if not item <= entry:
                    yield entry
            return

        # No decision yet, emit current entry.
        yield entry

class SubsumingQueue:
    '''
    A subsuming queue for elements of a partial order.
    Existing queue entries can be replaced by items that have priority over them.

    Queue invariant:
    No two entries have comparable priority.
    '''
    def __init__(self):
        self.mutex = threading.Lock()
        self.inhabited = threading.Condition(self.mutex)
        self.queue = iter(list())

    def add(self, item):
        '''
        Add an item to the queue.

        Does not change the queue if it already contains an equivalent element.
        Evicts all entries the item has priority over.
        If evictions occur, the  first evicted entry is replaced with new item.

        Adding is constant time.
        The actual work happens in 'remove' when processing the iterator.
        '''
        with self.mutex:
            self.queue = rebuild_queue(iter(self.queue), item)
            self.inhabited.notify()

    def remove(self):
        '''
        Remove the front entry from the queue and return it.
        No remaining entry has priority comparable to the result.
        Waits until an entry becomes available.
        '''
        with self.mutex:
            self.inhabited.wait()
            return next(self.queue)
