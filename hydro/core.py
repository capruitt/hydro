import numpy as np, pandas as pd, matplotlib.pyplot as plt
from datetime import datetime
from matplotlib.ticker import FuncFormatter
from scipy.optimize import curve_fit
plt.style.use("seaborn-ticks")

def exp_curve(x, a, b):
    """Exponential curve used for rating curves"""
    return (a * x**b)

def r_squ(x, y, pred):
    """ 
    Coefficient of determination
    
    x: independent variable\n
    y: dependent variable\n
    pred: predicted values
    """
    a = 0.0
    b = 0.0
    ybar = np.mean(y)
    for i, yhat in zip(y, pred):
        a += (i - yhat)**2
        b += (i - ybar)**2
    return 1 - a / b

class RC(object):
    def __init__(self, stage, discharge):
        """
        Stage-Discharge rating curve
        
        stage: pandas series containing stage values correspoding to discharges\n
        discharge: pandas series containing discharge measurements
        """
        self.stage = stage
        self.discharge = discharge
        # curve_fit
        self.popt, self.pcov = curve_fit(exp_curve, self.stage, self.discharge)
        # r-squared
        self.pred = [exp_curve(j, self.popt[0], self.popt[1]) for j in self.stage]
        self.r = r_squ(self.stage, self.discharge, self.pred)

    def Q(self, allstages):
        """ Compute discharges for entire series of stages"""
        return list(map(lambda x: round(exp_curve(x, self.popt[0], self.popt[1]), 3), allstages))

    def plot(self, title='Rating Curve', log=True):
        """ plot the rating curve """
        fig = plt.figure()
        ax1 = fig.add_subplot(111, facecolor='#E3E3E3')
        plt.grid(True, which='both', color='w', ls='-', zorder=0)
        ax1.scatter(self.stage, self.discharge, color='k', s=10)
        ax1.set_ylabel(r'Discharge, cfs')
        ax1.set_xlabel(r'Stage, ft')
        if log:
            ax1.set_ylim(0.01, 100)
            ax1.set_yscale('log'); ax1.set_xscale('log')                              # log scale x and y
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda y,pos: ('{{:.{:1d}f}}'.format(int(np.maximum(-np.log10(y),0)))).format(y)))
            ax1.xaxis.set_major_formatter(FuncFormatter(lambda y,pos: ('{{:.{:1d}f}}'.format(int(np.maximum(-np.log10(y),0)))).format(y)))
        plt.title(title)
        ax1.set_axisbelow(True)         # puts grid below plot

        # write the equation in the plot
        ax1.text(0.05, 0.7, f'y = {self.popt[0]:.3f}x^{self.popt[1]:.3f}',
                 fontsize=15, transform=ax1.transAxes)
        # draw the model line
        line = np.linspace(min(self.stage), max(self.stage), 100)
        ax1.plot(line, exp_curve(line, self.popt[0], self.popt[1]), color='k')
        plt.show()

class Discharge(object):
    def __init__(self, time, Q, rain=[]):
        """
        time: timeseries
        Q: discharge values
        """
        self.time = time
        self.Q = Q
        self.rain = rain
    
    def dailyQ(self, method='mean'):
        """
        Calculates the daily flow of a set of disharge data.
        
        Method specifies the method of aggregating each day -- either by 'mean'
        or by 'sum'. Default is mean.\n
        Returns daily flow and day in a dataframe.
        """
        daily = pd.DataFrame({'Q':self.Q, 'time':self.time})
        daily['day'] = daily.time.apply(lambda x: datetime(x.year, x.month, x.day))
        if method == 'mean':
            daily = pd.DataFrame(daily.groupby(['day'])['Q'].mean())
            daily['meanQ'] = daily['Q']
            del daily['Q']
        elif method == 'sum':
            daily = pd.DataFrame(daily.groupby(['day'])['Q'].sum())
            daily['sumQ'] = daily['Q']
            del daily['Q']
        daily.reset_index(inplace=True)
        return daily

    def RB_Flashiness(self):
        """Richards-Baker Flashiness Index for a series of daily mean discharges."""
        Q = self.dailyQ().meanQ
        Qsum = np.sum(Q)      # sum of daily mean discharges
        Qpath = 0.0
        for i in range(len(Q)):
            if i == 0:
                Qpath = Q.iloc[i]   # first entry only
            else:
                Qpath += np.abs(Q.iloc[i] - Q.iloc[i-1])  # sum the absolute differences of the mean discharges
        return Qpath/Qsum


    def flow_duration(self, plot=False):
        """
        Creates the flow duration curve for a discharge dataset. Returns a pandas
        series whose index is the discharge values and series is exceedance probability.
        """
        fd = pd.Series(self.Q).value_counts()               # frequency of unique values
        fd.sort_index(inplace=True)                         # sort in order of increasing discharges
        fd = fd.cumsum()                                    # cumulative sum of frequencies
        fd = fd.apply(lambda x: 100 - x/fd.max() * 100)     # normalize
        fd = pd.DataFrame(fd.reset_index())
        fd['exeedance_prob'] = fd['index']; del fd['index']
        
        if plot:
            import probscale # flow duration curves use a probability scale for the x axis
            fig = plt.figure(figsize=[8, 10])
            ax1 = fig.add_subplot(111, facecolor='#E3E3E3')
            plt.grid(True, which='both', color='w', ls='-', zorder=0)
            ax1.plot(fd['discharge_cfs'], fd['exeedance_prob'], 'x', ls='', 
                     color='k', label='Total Flow', ms=5)
            
            # set y axis to log scale and x axis to probability scale
            ax1.set_yscale('log')
            ax1.set_xscale('prob') # from import probscale
            plt.xticks([.01,.1,.5,1,2,5,10,20,30,40,50,60,70,80,90,95,98,99,99.5,99.9,99.99],
                       rotation='vertical')
            plt.legend()
            plt.title('Flow Duration Curve')
            plt.ylabel('Flow (cfs)')
            plt.xlabel('Percentage of time flow was equaled or exceeded')
            plt.show()
        return fd

    def Lyne_Hollick(self, alpha=.925, direction='f'):
        """
        Recursive digital filter for baseflow separation. Based on Lyne and Hollick, 1979.
        
        series : array of discharge measurements\n
        alpha : filter parameter\n
        direction : (f)orward or (r)everse calculation
        """
        # first looks to see if there has alread been a run
        try:
            Q = np.array(self.bflow)
        except:
            Q = np.array(self.Q)
        f = np.zeros(len(Q))
        if direction == 'f':
            for t in np.arange(1,len(Q)):
                # algorithm
                f[t] = alpha * f[t-1] + (1 + alpha)/2 * (Q[t] - Q[t-1])
                # to prevent negative values
                if Q[t] - f[t] > Q[t]:
                    f[t] = 0
        elif direction == 'r':
            for t in np.arange(len(Q)-2, 1, -1):
                f[t] = alpha * f[t+1] + (1 + alpha)/2 * (Q[t] - Q[t+1])
                if Q[t] - f[t] > Q[t]:
                    f[t] = 0
        # adds the baseflow to self variables so it can be called recursively
        self.bflow = np.array(Q - f) 
        return np.array(Q - f)

    def Eckhardt(self, alpha=.98, BFI=.80):
        """
        Recursive digital filter for baseflow separation. Based on Eckhardt, 2004.\n
        series : array of discharge measurements\n
        alpha : filter parameter\n
        BFI : BFI_max (maximum baseflow index)
        """
        # first looks to see if there has alread been a run
        try:
            Q = np.array(self.bflow)
        except:
            Q = np.array(self.Q)
        f = np.zeros(len(Q))
        f[0] = Q[0]
        for t in np.arange(1,len(Q)):
            # algorithm
            f[t] = ((1 - BFI) * alpha * f[t-1] + (1 - alpha) * BFI * Q[t]) / (1 - alpha * BFI)
            if f[t] > Q[t]:
                f[t] = Q[t]
        # adds the baseflow to self variables so it can be called recursively
        self.bflow = f
        return f
    
    def plot(self, addseries=[], log=True):
        """
        Quick plot with or without rain data.\n
        If you wish to plot more than one series to compare them, use addseries 
        to list in order of [time, Q, ...] for each additional series.
        """
        fig = plt.figure()
        ax1 = fig.add_subplot(111, facecolor='#E3E3E3')
        plt.grid(True, which='both', color='w', ls='-', zorder=0)
        ax1.plot(self.time, self.Q, label='Series1')
        if len(self.rain) != 0:
            ax2 = ax1.twinx()
            ax2.plot(self.time, self.rain, alpha=.5, c='b', lw=1, label='Rain')
            ax2.set_ylim(1, 0)
            ax2.set_ylabel(r'Rain, in')
        ax1.set_ylabel('Discharge, cfs')
        ax1.set_xlabel('Stage, ft')
        # log scale for y axis
        if log:
            ax1.set_yscale('log')
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda y,pos: ('{{:.{:1d}f}}'.format(int(np.maximum(-np.log10(y),0)))).format(y)))
        # add ablity to plot multiple time series
        more = len(addseries)
        while more > 0:
            ax1.plot(addseries[more-2], addseries[more-1], 
                     label=f'Series{int(len(addseries)/2-more/2 +2)}')
            more -= 2
        ax1.legend(loc='best')
        plt.show()


def sinuosity(Easting, Northing, length, distance):
    """Calculates sinuosity at each data point. Easting and Northing are lat/longs
    projected into measureable units. Length is distance to calculate the
    sinuosity on either side of points. Distance is the stream distance between data points.

    To calculate sinuosity for an entire stream, use the start and end points in
    'Easting' and 'Northing', set length to 2 * stream length, and distance to
    stream length.
    """
    pnts = int(length/distance) # number of points for each reach
    East = np.array(Easting)
    North = np.array(Northing)

    if pnts / 2 == 1:  # if the calculation is only for two points
        return distance / np.sqrt(np.abs(East[0] - East[1])**2
                 + np.abs(North[0] - North[1])**2)
    else:

        # Calculate sinuosity: stream length / straight line distance
        sin = np.zeros(len(East))
        l = len(East)
        b = pnts * 2 * distance  # calculates stream distance for pnts in middle of dataset
        for i in range(int(l)):
            if i < pnts: # first few points
                a = (i + pnts) * distance # calculates stream distance
                sin[i] = a / np.sqrt(np.abs(East[i+pnts] - East[0])**2
                         + np.abs(North[i+pnts] - North[0])**2)
            elif len(sin)-i < pnts +1: # last few points
                a = (len(sin)-i + pnts) * distance
                sin[i] = a /np.sqrt(np.abs(East[len(sin)-1] - East[i-pnts])**2
                         + np.abs(North[len(sin)-1] - North[i-pnts])**2)
            else: # most points are evaluated here
                sin[i] = b / np.sqrt(np.abs(East[i+pnts] - East[i-pnts])**2
                         + np.abs(North[i+pnts] - North[i-pnts])**2)
        return sin

def Profile_smoothing(elevation, distance, plot=False):
    """Removes the 'bumps' present in an elevation profile caused by roads &
     imperfections in DEMs. Data must be arranged from highest elevation to lowest.
     
     Set plot=True to graph the resulting profile
    """
    elevation = np.array(elevation)
    output_elevation = np.zeros(len(elevation)); output_elevation[0]=elevation[0]
    elevation[-1] = min(elevation)
    i=1
    while i < len(elevation):                    # loops through elevation dataset
        if elevation[i] > elevation[i-1]:             # if the current value is greater than the previous,
            j=i
            while j < len(elevation)-1:          # loop through the remaining data...
                j = j+1
                if elevation[j] <= elevation[i-1]:    # to find the next point that is lower or equal to the last datum.
                    for indx,k in enumerate(range(i, j)):       # changes the incorrect data...
                        adj = np.linspace(elevation[i-1], elevation[j], num=len(elevation[i:j]), endpoint=False)   # to a linear interp.
                        output_elevation[k] = adj[indx]
                    break       # exits if statement
            i=j-1               # starting point for the next iteration
        else:
            output_elevation[i] = elevation[i]   # if the elevation is less than or equal to the previous, that point kept
        i = i+1                     # keeps the while loop interating to next datum
        
    if plot:
            fig = plt.figure(figsize=(20,3))
            ax1 = fig.add_subplot(111)
            ax1.plot(distance, output_elevation, label='Elevation Profile')
            ax1.invert_xaxis()
            ax1.set_ylabel('Elevation')                    # y label
            ax1.set_xlabel('Distance from mouth')          # x label
            plt.title("Longitudinal Profile")       # title
            plt.show()

    return output_elevation
