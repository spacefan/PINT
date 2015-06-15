# This program is designed to predict the pulsar's phase and pulse-period over a 
# given interval using polynomial expansion. The return will be some necessary
# information and the polynomial coefficients  

import functools
from ..phase import Phase
import numpy as np
import pint.toa as toa 
import pint.utils as utils
import astropy.units as u
import astropy.constants as const
from .parameter import Parameter
from .timing_model import TimingModel, MissingParameter, Cache
import astropy.table as table
from astropy.io import registry
import numpy.polynomial.chebyshev as cheb
import math 

class polycoEntry:
    """
    Polyco Entry class:
    A Class for one Polyco entry.
    Referenced from polyco.py authored by 
        Paul S. Ray <paul.ray@nrl.navy.mil>
        Matthew Kerr <matthew.kerr@gmail.com>
    Parameters
    ---------
    tmid : float 
        Middle point of the time span in mjd
    mjdspan : float
        Time span in mjd
    rphase : float
        Reference phase
    f0 : float
        Reference spin frequency
    ncoeff : int
        Number of coefficients
    obs : str
        Observatory code
    """
    def __init__(self,tmid,mjdspan,rphaseInt,rphaseFrac,f0,ncoeff,coeffs,obs):
        self.tmid = tmid
        self.mjdspan = mjdspan
        self.tstart = np.longdouble(tmid) - np.longdouble(mjdspan)/2.0
        self.tstop = np.longdouble(tmid) + np.longdouble(mjdspan)/2.0
        self.rphase = Phase(rphaseInt,rphaseFrac)
        self.f0 = np.longdouble(f0)
        self.ncoeff = ncoeff
        self.coeffs = np.longdouble(coeffs)
        self.obs = obs
    
    def __str__(self):
        return("Middle Point mjd : "+repr(self.tmid)+"\n"+
               "Time Span in mjd : "+repr(self.mjdspan)+"\n"+
               "Reference Phase : "+repr(self.rphase)+"\n"+
               "Number of Coefficients : "+repr(self.ncoeff)+"\n"+
               "Coefficients : "+repr(self.coeffs))
        
    def valid(self,t):
        '''Return True if this polyco entry is valid for the time given (MJD)'''
        return t>=(self.tmid-self.mjdspan/2.0) and t<(self.tmid+self.mjdspan/2.0)

    def evalabsphase(self,t):
        '''Return the phase at time t, computed with this polyco entry'''
        dt = (t-self.tmid)*1440.0
        # Compute polynomial by factoring out the dt's
        p = self.coeffs[self.ncoeff-1]
        phase = Phase(self.coeffs[self.ncoeff-1])
        for i in range(self.ncoeff-2,-1,-1):
            p = self.coeffs[i]+dt*p
            pI = Phase(dt*phase.int)
            pF = Phase(dt*phase.frac)
            c = Phase(self.coeffs[i])
            phase = pI+pF+c
            print self.coeffs[i],phase.int,p
         
        # Add DC term
        phase += self.rphase +Phase(dt*60.0*self.f0)
        return(phase)

    def evalabsphaseB(self,t):
        '''Return the phase at time t, computed with this polyco entry'''
        dt = (t-self.tmid)*1440.0
        # Compute polynomial by factoring out the dt's
        phase = self.coeffs[self.ncoeff-1]
        for i in range(self.ncoeff-2,-1,-1):
            phase = self.coeffs[i] + dt*phase
        # Add DC term
        phase += self.rphase + dt*60.0*self.f0
        return(phase)

    def evalphase(self,t):
        '''Return the phase at time t, computed with this polyco entry'''
        return(self.evalabsphase(t).frac)

    def evalfreq(self,t):
        '''Return the freq at time t, computed with this polyco entry'''
        dt = (t-self.tmid)*1440.0
        s = 0.0
        for i in range(1,self.ncoeff):
            s += np.longdouble(i) * self.coeffs[i] * dt**(i-1)
        freq = self.f0 + s/60.0
        return(freq)

    def evalfreqderiv(self,t):
        """ Return the frequency derivative at time t."""
        dt = (t-self.tmid)*1440.0
        s = 0.0
        for i in range(2,self.ncoeff):
            s += float(i) * float(i-1) * self.coeffs[i] * dt**(i-2)
        freqd = s/(60.0*60.0)
        return(freqd)

# Read polycos file data to table 
def tempo_polyco_table_reader(filename):
    """
    Read tempo style polyco file to an astropy table
    
    Parameters
    ---------
    filename : str
        Name of the input poloco file.

    Tempo style:  
    The polynomial ephemerides are written to file 'polyco.dat'.  Entries
    are listed sequentially within the file.  The file format is:

    Line  Columns     Item
    ----  -------   -----------------------------------
     1       1-10   Pulsar Name
            11-19   Date (dd-mmm-yy)
            20-31   UTC (hhmmss.ss)
            32-51   TMID (MJD)
            52-72   DM
            74-79   Doppler shift due to earth motion (10^-4)
            80-86   Log_10 of fit rms residual in periods
     2       1-20   Reference Phase (RPHASE)
            21-38   Reference rotation frequency (F0)
            39-43   Observatory number 
            44-49   Data span (minutes)
            50-54   Number of coefficients
            55-75   Observing frequency (MHz)
            76-80   Binary phase
     3*      1-25   Coefficient 1 (COEFF(1))
            26-50   Coefficient 2 (COEFF(2))
            51-75   Coefficient 3 (COEFF(3))

    * Subsequent lines have three coefficients each, up to NCOEFF

    One polyco file could include more then one entrie

    The pulse phase and frequency at time T are then calculated as:
    DT = (T-TMID)*1440
    PHASE = RPHASE + DT*60*F0 + COEFF(1) + DT*COEFF(2) + DT^2*COEFF(3) + ....
    FREQ(Hz) = F0 + (1/60)*(COEFF(2) + 2*DT*COEFF(3) + 3*DT^2*COEFF(4) + ....)
        
    Reference:
        http://tempo.sourceforge.net/ref_man_sections/tz-polyco.txt    
    """    
    f = open(filename, "r")
    entries=[]
    # Read entries to the end of file
    while True:
        # Read first line
        line1 = f.readline()
        if len(line1) == 0:
            break

        fields = line1.split()
        psrname = fields[0].strip()
        date = fields[1].strip()
        utc = fields[2]
        tmid = np.longdouble(fields[3])
        dm = float(fields[4])
        doppler = float(fields[5])
        logrms = float(fields[6])
        # Read second line
        line2 = f.readline()
        fields = line2.split()
        refPhaseInt,refPhaseFrac = fields[0].split('.')
        refPhaseInt = np.longdouble(refPhaseInt)
        refPhaseFrac = np.longdouble('.'+refPhaseFrac)
        if refPhaseInt<0:
            refPhaseFrac = -refPhaseFrac

        refF0 = np.longdouble(fields[1])
        obs = fields[2]
        mjdSpan = np.longdouble(fields[3])/(60*24)   # Here change to constant
        nCoeff = int(fields[4])
        obsfreq = float(fields[5].strip())

        try:
            binaryPhase = np.longdouble(fields[6])
        except:
            binaryPhase = 0.0

        # Read coefficients 
        nCoeffLines = nCoeff/3

        if nCoeff%3>0:
            nCoeffLines += 1
        coeffs = []

        for i in range(nCoeffLines):
            line = f.readline()
            for c in line.split():
                coeffs.append(np.longdouble(c))
        coeffs = np.array(coeffs)
        entry = polycoEntry(tmid,mjdSpan,refPhaseInt,refPhaseFrac,refF0,nCoeff,coeffs,obs)

        entries.append((psrname, date, utc, tmid, dm, doppler, logrms,
                        binaryPhase, obsfreq,entry))

    # Construct the polyco data table
    pTable = table.Table(rows = entries, names = ('psr','date','utc','tmid','dm',
                                            'dopper','logrms','binary_phase',
                                            'obsfreq','entry'), 
                                            meta={'name': 'Ployco Data Table'})
    return pTable
    #return entries

def register_polyco_tabel_reader(formatName):

    pass

class Polycos(TimingModel):
    """
    A class for polycos model. Ployco is a fast phase calculator. It fits a set 
    of data using polynomials.


    """
    def __init__(self): 
        super(Polycos, self).__init__()
        self.mjdMid = None
        self.mjdSpan = None
        self.tStart = None
        self.tStop = None
        self.ncoeff = None
        self.coeffs = None
        self.obs = None
        self.fileName = None
        self.fileFormat = None
        self.newFileName = None
        self.dataTable = None
        self.polycoFormat = [{'format': 'tempo', 
                            'read_method' : tempo_polyco_table_reader,
                            'write_method' : None},]
        
        # Register the table built-in reading and writing format
        for fmt in self.polycoFormat:
            if fmt['format'] not in registry.get_formats()['Format']:
                if fmt['read_method'] != None:
                   registry.register_reader(fmt['format'], table.Table,
                                            fmt['read_method'])
                    
                if fmt['write_method'] != None:
                    registry.register_writer(fmt['format'], table.Table, 
                                            fmt['write_method'])
               
        
        

    def setup(self): #, ncoeff, mjd_mid, mjd_span, oldPolycoFile = None):
        super(Polycos, self).setup()
        
    	'''
        self.mjdMid = mjd_mid
    	self.mjdSpan = mjd_span
    	self.tstart = self.mjdMid - float(mjdSpan)/2.0
    	self.tstop = self.mjdMid + float(mjdSpan)/2.0
    	self.oldFileName = oldPolycoFile
    	
    	if self.olfFileName == None:
    		self.newFileName = "polyco_"+self.psr.value + ".dat" 
    	else:
    		self.newFileName =  "new_"+oldPolycoFile
        '''
    def add_polyco_file_format(self, formatName, methodMood, readMethod = None, 
                                writeMethod = None):
        """
        Add a polyco file format and its reading/writting method to the class. 
        Then register it to the table reading. 
        Parameters
        ---------
        formatName : str
            The name for the format.
        methodMood : str
            ['r','w','rw']. 'r'  represent as reading 
                            'w'  represent as writting
                            'rw' represent as reading and writting
        readMethod : method
            The method for reading the file format.
        writeMethod : method
            The method for writting the file to disk.
        """
        # Check if the format already exist. 
        if (formatName in [f['format'] for f in self.polycoFormat] 
            or formatName in registry.get_formats()['Format']):
            errorMssg = 'Format name \''+formatName+ '\' is already exist. '
            raise Exception(errorMssg)

        pFormat = {'format' : formatName}

        if methodMood == 'r':
            if readMethod == None:
                raise BaseException('Argument readMethod should not be \'None\'.')
            
            pFormat['read_method'] = readMethod
            pFormat['write_method'] = writeMethod
            registry.register_reader(pFormat['format'], table.Table, 
                                    pFormat['read_method'])
        elif methodMood == 'w':
            if writeMethod == None:
                raise BaseException('Argument writeMethod should not be \'None\'.')
           
            pFormat['read_method'] = readMethod
            pFormat['write_method'] = writeMethod
            registry.register_writer(pFormat['format'], table.Table, 
                                    pFormat['write_method'])
        elif methodMood == 'rw':
            if readMethod == None or writeMethod == None:
                raise BaseException('Argument readMethod and writeMethod' 
                                    'should not be \'None\'.')

            pFormat['read_method'] = readMethod
            pFormat['write_method'] = writeMethod

            registry.register_reader(pFormat['format'], table.Table, 
                                    pFormat['read_method'])
            registry.register_writer(pFormat['format'], table.Table, 
                                    pFormat['write_method'])

        self.polycoFormat.append(pFormat)
        

    def generate_polycos(self, mjdStart, mjdEnd, parFile, obs, 
                         segLength, ncoeff, obsFreq, maxha,
                         method = "TEMPO"):
        """
        Generate the polyco file data file. 

        Parameters
        ---------
        mjd : 

        """
        self.read_parfile(parFile)
        mjdStart = mjdStart*u.day
        mjdEnd = mjdEnd*u.day
        timeLength = mjdEnd-mjdStart
        segLength = segLength*u.min

        coeffsList = []
        nodesList = []
        refPhaseList = []
        entryList = []
        numSeg = timeLength/segLength.to('day')
        domainList = []
        domain = [mjdStart, mjdStart+segLength]
        domainList.append((domain[0],domain[1]))


        while domain[1]<mjdEnd:
            domain[0] = domain[1]

            if mjdEnd-domain[0]< segLength:
                domain[1] = mjdEnd
            else:
                domain[1] = domain[1] +segLength
            domainList.append((domain[0],domain[1]))
        
    	# generate the ploynomial coefficents
    	if method == "TEMPO":
            nodeCoeff = np.zeros(ncoeff)
            nodeCoeff[-1] = 1.0
    	# Using tempo1 method to create polycos
            for i in range(len(domainList)):
                tmid = (np.longdouble(domainList[i][1])+np.longdouble(domainList[i][0]))/2.0
                print tmid
                toaMid = toa.get_TOAs_list([toa.TOA((np.modf(tmid)[1], 
                                    np.modf(tmid)[0]),obs = obs,
                                    freq = obsFreq),])
                refPhase = self.phase(toaMid.table)
                #refF0 = self.d_phase_d_toa(toaMid.table)  FIXME ???
                #tmid,mjdSpan,refPhase,refF0,nCoeff,coeffs,obs
                mjdSpan = (domainList[i][1]-domainList[i][0])

                nodes = cheb.chebroots(nodeCoeff)  # Here nodes is in the interval (-1,1)
                nodesMjd = ((np.longdouble(nodes)-(-1.0))*(domainList[i][1]
                            -domainList[i][0]))/2.0 + domainList[i][0] # Rescale to the domain
                toaList = []
                for toaNode in nodesMjd.value:
                    toaList.append(toa.TOA((np.modf(toaNode)[1], 
                                    np.modf(toaNode)[0]),obs = obs,
                                    freq = obsFreq))
                toas = toa.get_TOAs_list(toaList)

                ph = self.phase(toas.table)
                print ph
                rdcPhase = ph-refPhase
                print rdcPhase
                dnodesMjd = nodesMjd.value.astype(float)  # Trancate to double
                drdcPhase = (rdcPhase.int+rdcPhase.frac).astype(float)
                coeffs = cheb.chebfit(dnodesMjd*86400.0,drdcPhase,ncoeff)

                entry = polycoEntry(tmid,mjdSpan.value,refPhase.frac+refPhase.int,self.F0.value,ncoeff,coeffs,obs)
                entryList.append((self.PSR.value, '27-Dec-03', 10000.00, tmid, self.DM.value,0,0,0,obsFreq,entry))

            pTable = table.Table(rows = entryList, names = ('psr','date','utc','tmid','dm',
                                        'dopper','logrms','binary_phase',
                                        'obsfreq','entry'), 
                                        meta={'name': 'Ployco Data Table'})
            self.dataTable = pTable
                
    	else:
    		#  Reading from an old polycofile
    		pass
        

    def read_polyco_file(self,filename,format):
        """
        Read polyco file from one type of format to a table.

        Parameters
        ---------
        filename : str
            The name of the polyco file.
        format : str
            The format of the file.
        """
        self.fileName = filename

        if format not in [f['format'] for f in self.polycoFormat]:
            raise Exception('Unknown polyco file format \''+ format +'\'\n'
                            'Plese use function \'self.add_polyco_file_format()\''
                            ' to register the format\n')
        else:
            self.fileFormat = format

        self.dataTable = table.Table.read(filename, format = format) 
        
    def find_entry(self,t):
        if not isinstance(t, np.ndarray) and not isinstance(t,list):
            t = np.array([t,])
        # Check if polyco table exist 
        try:
            lenEntry = len(self.dataTable)
            if lenEntry == 0:
                errorMssg = "No sufficent polyco data. Plese read or generate polyco data correctlly."
                raise AttributeError(errorMssg)

        except: 
            errorMssg = "No sufficent polyco data. Plese read or generate polyco data correctlly."
            raise AttributeError(errorMssg)
    
        if self.tStart is None or self.tStop is None:
            self.tStart = np.array([self.dataTable['entry'][i].tstart for i in range(lenEntry)])
            self.tStop = np.array([self.dataTable['entry'][i].tstop for i in range(lenEntry)])
        
        # Check if t in the polyco domain
        
        if np.min(t) < self.tStart[0] or np.max(t) > self.tStop[-1]:
            errorMssg = "Input time should be in the range of "+str(self.tStart[0])+" and "+str(self.tStop[-1])
            raise ValueError(errorMssg)

        startIndex = np.searchsorted(self.tStart,t)
      
        entryIndex = startIndex-1
        overFlow = np.where(t > self.tStop[entryIndex])[0]
        if overFlow.size!=0: 
            errorMssg = ("Input time"+str(t[overFlow])+"may be not coverd by entry start with "
                        +str(self.tStart[overFlow])+ " and end with "+str(self.tStop[overFlow]))
            raise ValueError(errorMssg)

        return entryIndex
        
    def eval_phase(self,t):
        if not isinstance(t, np.ndarray) and not isinstance(t,list):
            t = np.array([t,])

        entryIndex = self.find_entry(t)
        phase = np.longdouble(np.zeros((len(t),1)))
        for i,time in enumerate(t):
            absPhase[i] = self.dataTable['entry'][entryIndex[i]].evalabsphase(time).frac[0]
        return phase

    def eval_abs_phase(self,t):
        if not isinstance(t, np.ndarray) and not isinstance(t,list):
            t = np.array([t,])

        entryIndex = self.find_entry(t)
        absPhase = np.longdouble(np.zeros((len(t),2)))
        
        for i,time in enumerate(t):
            absPhase[i][0] = self.dataTable['entry'][entryIndex[i]].evalabsphase(time).int[0]
            absPhase[i][1] = self.dataTable['entry'][entryIndex[i]].evalabsphase(time).frac[0]
        
        return Phase(absPhase[:,0],absPhase[:,1])

    def eval_spin_freq(self,t):
        entryIndex = self.find_entry(t)
        spinFreq = self.dataTable['entry'][entryIndex].evalfreq(t)
        return spinFreq


