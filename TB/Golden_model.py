class GoldenMemoryController:
    def __init__(self):
        self.memory = {}          # Represents the physical DRAM
        self.prefetch_buffer = {} # Represents the 16-entry PB
        self.last_addr = 0
        self.last_stride = 0
        self.confidence = 0

    def write_memory(self, addr, data):
        """Simulate an AXI demand write."""
        self.memory[addr] = data
        # Inwrite invalidates prefetch buffer if addresses overlap
        if addr in self.prefetch_buffer:
            del self.prefetch_buffer[addr]

    def read_memory(self, addr):
        """Simulate an AXI demand read and return expected data."""
        # Check PB first
        if addr in self.prefetch_buffer:
            data = self.prefetch_buffer.pop(addr) # Hit-and-invalidate
        else:
            # Fetch from main memory (default to 0 if uninitialized)
            data = self.memory.get(addr, 0)
        
        self._update_stride_engine(addr)
        return data

    def _update_stride_engine(self, addr):
        """Software model of the Stride Prefetcher."""
        current_stride = addr - self.last_addr
        
        if current_stride == self.last_stride and current_stride != 0:
            if self.confidence < 3:
                self.confidence += 1
            if self.confidence >= 2:
                # Trigger speculative fetch in golden model
                pref_addr = addr + current_stride
                self.prefetch_buffer[pref_addr] = self.memory.get(pref_addr, 0)
        else:
            self.last_stride = current_stride
            self.confidence = 0
            
        self.last_addr = addr