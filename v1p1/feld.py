"""
Ein Feld repraesentiert ein Datenfeld inkl. dessen Acheneinheiten und Beschriftungen. Die Idee ist, dass ein Feld direkt geplottet oder als csv expoertiert werden kann.
"""


from . import *
from _Constants import *
import copy

__all__ = ['Feld']

class Feld(_Constants):
    """
    Repraesentiert ein Feld, das spaeter dirket geplottet werden kann.
    """
        
    def __init__(self, matrix):
        self.matrix = np.array(matrix, dtype='float64')
        self.grid_nodes = []
        self.axesnames = []
        self.axesunits = []
        for i in xrange(self.dimensions()):
            self.addaxis()
        self.name = 'unbekannt'
        self.name2 = ''
        self.label = ''
        self.unit = None           
        self.zusatz = ''
        self.textcond = ''
        self._grid_nodes_linear = True #None bedeutet unbekannt


    def __str__(self):
        return '<Feld '+self.name +' '+str(self.matrix.shape)+'>'
        
        
    #Operator overloading    
    def __iadd__(self, other):
        if isinstance(other, Feld):
            self.matrix += other.matrix
        else:
            self.matrix += other
        return self
        
    def __add__(self, other):
        ret = copy.deepcopy(self)
        ret += other
        return ret
        
    def __neg__(self):
        ret = copy.deepcopy(self)
        ret.matrix *= -1
        return ret
        
    def __isub__(self, other):
        if isinstance(other, Feld):
            self.matrix -= other.matrix
        else:
            self.matrix -= other
        return self
        
    def __sub__(self, other):
        ret = copy.deepcopy(self)
        ret -= other
        return ret 

    def __pow__(self, other):
        ret = copy.deepcopy(self)
        ret.matrix = self.matrix**other
        return ret
 
    def __imul__(self, other):
        if isinstance(other, Feld):
            self.matrix *= other.matrix
        else:
            self.matrix *= other
        return self
        
    def __mul__(self, other):
        ret = copy.deepcopy(self)
        ret *= other
        return ret
        
    def __abs__(self):
        ret = copy.deepcopy(self)
        ret.matrix = np.abs(ret.matrix)
        return ret
        
    # self /= other: Normierung implementieren
    def __idiv__(self, other):
        if isinstance(other, Feld):
            self.matrix /= other.matrix
        else:
            self.matrix /= other
        return self
        
    def __div__(self, other):
        ret = copy.deepcopy(self)
        ret /= other
        return ret    

        
    def addaxis(self, name='', unit='?'):
        self.axesnames.append(name)
        self.axesunits.append(unit)
        self.grid_nodes.append(np.array([0,1]))
        return self
    
    def extent(self):
        ret = []
        for traeger in self.grid_nodes:
            ret.append(traeger[0])
            ret.append(traeger[-1])
        return ret
        
    def grid_nodes_linear(self, force=True):
        """
        Testet, ob die grid_nodes linear verteielt sind. Ist das der Fall, reicht es auch nur mit extent() zu plotten.
        Ausgabe ist die Liste der Varianzen der Grid Node Abstaende.
        """
        if self._grid_nodes_linear == None or force:
            self._grid_nodes_linear = all([np.var(np.diff(gn)) < 1e-7 for gn in self.grid_nodes ])
        return self._grid_nodes_linear 
            
        
        
    def setgrid_node(self, axis, grid_node):
        if axis < self.dimensions():
            self.grid_nodes[axis] = np.float64(grid_node)
            self._grid_nodes_linear = None
        return self
        
    def setgrid_node_fromextent(self, extent):
        """
        Errechnet eigene Werte fuer grid_node, falls nur der extent gegeben wurde.
        Vereinfacht Kompatibilitaet, aber es ist empfohlen setgrid_node(self, axis, grid_node) direkt aufzurufen. 
        """
        assert not len(extent)%2, 'len(extent) muss gerade sein (2 Eintraege pro Achse)' 
        for dim in xrange(self.dimensions()):
            self.setgrid_node(dim, np.linspace(extent[2*dim], extent[2*dim + 1], self.matrix.shape[dim] + 1))
        return self
        
    def setgrid_node_fromgrid(self, axis, grid):
        """
        grid_node beinhaltet die Kanten des Grids. In 1D gehoert also zu einem Datenfeld der Laenge 1000 ein grid_node Vektor der Laenge 1001.
        grid beinhaltet die Positionen. In 1D gehoert also zu einem Datenfeld der Laenge 1000 ein grid Vektor der Laenge 1000.
        """
        gn = np.convolve(grid, np.ones(2)/2.0, mode='full')
        gn[0] = grid[0] + 2 * (grid[0] - gn[1])
        gn[-1] = grid[-1] + 2 * (grid[-1] - gn[-2])
        return self.setgrid_node(axis, gn)
        
    def ausschnitt(self, ausschnitt):
        if self.dimensions() == 0:
            return
        if self.extent != None:
            raise Exception('extent kann nicht geaendert werden, wenn der aktuelle extent unbekannt ist.')
        self.matrix = _Constants.datenausschnitt(self.matrix, self.extent, ausschnitt)
        self.extent = ausschnitt
    
    def dimensions(self):
        return len(self.matrix.shape)
        
    def savename(self):
        return self.name + ' ' + self.name2

    def mikro(self):
        #self.grid_nodes *= 1e6
        map(lambda x: x*1e6, self.grid_nodes)
        self.axesunits = ['$\mu $'+x for x in self.axesunits]
        return self        
        
    def grid(self):
        """
        Creates lists containing X and Y coordinates of the data (in 2D case). Those can be directly parsed to matplotlib.pyplot.pcolormesh
        
        Also von grid_node (Laenge N+1)  auf grid (Laenge N) konvertieren. 
        """
        return tuple([np.convolve(gn, np.ones(2)/2.0, mode='valid') for gn in self.grid_nodes])

    def setallaxes(self, name=None, unit=None):
        def setlist(arg):
            if isinstance(arg,list):
                return [arg[dim] for dim in xrange(self.dimensions())]
            else:
                return [arg for dim in xrange(self.dimensions())]
        if name:
              self.axesnames = setlist(name)
        if unit:
            self.axesunits = setlist(unit)
        return self
        
    def setallaxesspacial(self):
        """
        Alle (vorhandenen) Achsen werden zu Raumachsen.
        """
        self.setallaxes(name=['X','Y','Z'], unit=[r'$m$', r'$m$', r'$m$'])

    def mean(self, axis=-1):
        if self.dimensions() == 0:
            return self
        self.matrix=np.mean(self.matrix, axis=axis)
        self.axesunits.pop(axis)
        self.axesnames.pop(axis)
        if self.extent() != None:
            self.grid_nodes.pop(axis)
            #self.extent = np.delete(self.extent(), [2*axis, 2*axis+1])
        return self

    def topolar(self, extent=None, shape=None, angleoffset=0):
        """Transformiert die Aktuelle Darstellung in Polardarstellung. extent und shape = None bedeutet automatisch.
extent=(phimin, phimax, rmin, rmax)"""
        ret = copy.deepcopy(self)
        if extent==None:
            extent=[-np.pi, np.pi,0, self.extent()[1]]
        extent=np.asarray(extent)
        if shape==None:
            shape = (1000, np.min((np.floor(np.min(self.matrix.shape) / 2), 1000)) )
        
        extent[0:2]=extent[0:2] - angleoffset
        ret.matrix = self.transfromxy2polar(self.matrix, self.extent(), np.roll(extent,2), shape).T
        extent[0:2]=extent[0:2] + angleoffset
    
        ret.setgrid_nodefromextent(extent)    
        if ret.axesnames[0].startswith('$k_') and ret.axesnames[1].startswith('$k_'):
            ret.axesnames[0]='$k_\phi$'
            ret.axesnames[1]='$|k|$'
        return ret

    def exporttocsv(self, dateiname):
        if self.dimensions() == 1:
            data = np.asarray(self.matrix)
            x = np.linspace(self.extent()[0], self.extent()[1], len(data))
            np.savetxt(dateiname, np.transpose([x, data]), delimiter=' ')
        elif self.dimensions() == 2:
            export = np.asarray(self.matrix)
            np.savetxt(dateiname, export)
        else:
            raise Exception('Not Implemented')


