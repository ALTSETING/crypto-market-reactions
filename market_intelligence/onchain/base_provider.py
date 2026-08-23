from abc import ABC,abstractmethod
class OnchainProvider(ABC):
    name="abstract";paid=False
    @abstractmethod
    def availability(self):raise NotImplementedError
    @abstractmethod
    def fetch(self,start,end):raise NotImplementedError
