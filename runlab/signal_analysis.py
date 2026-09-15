from __future__ import annotations

"""Signal-processing primitives for the telemetry workstation.

The GUI is intentionally not the owner of filtering or frequency analysis.
This module accepts engineering X/Y arrays, validates/resamples the timebase,
and returns deterministic NumPy results that can be regression-tested without
Qt. Raw telemetry is never modified in-place.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal


@dataclass
class UniformSignal:
    time_s: np.ndarray
    values: np.ndarray
    sample_rate_hz: float
    source_points: int
    resampled: bool


@dataclass
class FilterResult:
    time_s: np.ndarray
    values: np.ndarray
    sample_rate_hz: float
    kind: str
    cutoff_hz: tuple[float, ...]
    order: int
    resampled: bool


@dataclass
class SpectrumResult:
    frequency_hz: np.ndarray
    amplitude: np.ndarray
    sample_rate_hz: float
    resolution_hz: float
    source_points: int
    window: str
    detrended: bool


@dataclass
class PSDResult:
    frequency_hz: np.ndarray
    density: np.ndarray
    sample_rate_hz: float
    resolution_hz: float
    source_points: int
    window: str
    segment_points: int


@dataclass
class SpectrogramResult:
    frequency_hz: np.ndarray
    time_s: np.ndarray
    density: np.ndarray
    sample_rate_hz: float
    source_points: int
    window: str
    segment_points: int


def _finite_ordered(time_s, values):
    t=np.asarray(time_s,dtype=float).reshape(-1)
    y=np.asarray(values,dtype=float).reshape(-1)
    n=min(len(t),len(y)); t=t[:n]; y=y[:n]
    mask=np.isfinite(t)&np.isfinite(y)
    t=t[mask]; y=y[mask]
    if len(t)<3:
        raise ValueError('Signal analysis requires at least three finite time/value samples.')
    order=np.argsort(t,kind='stable'); t=t[order]; y=y[order]
    keep=np.r_[True,np.diff(t)>0]
    t=t[keep]; y=y[keep]
    if len(t)<3:
        raise ValueError('Signal analysis requires at least three unique increasing time samples.')
    return t,y,n


def uniform_time_signal(time_s, values, *, sample_rate_hz: Optional[float]=None, max_points: int=2_000_000) -> UniformSignal:
    """Return a finite uniformly sampled signal.

    The native median sample interval is retained when practical. Irregular
    logger clocks are linearly resampled; regularly sampled clocks are returned
    unchanged. A hard point cap prevents accidental multi-gigabyte allocations.
    """
    t,y,source_points=_finite_ordered(time_s,values)
    dt=np.diff(t)
    median_dt=float(np.median(dt))
    if not np.isfinite(median_dt) or median_dt<=0:
        raise ValueError('Cannot determine a positive telemetry sample interval.')
    inferred_rate=1.0/median_dt
    rate=float(sample_rate_hz) if sample_rate_hz is not None else inferred_rate
    if not np.isfinite(rate) or rate<=0:
        raise ValueError('Sample rate must be positive.')
    duration=float(t[-1]-t[0])
    points=int(np.floor(duration*rate))+1
    if points<3:
        raise ValueError('Signal duration is too short for requested sample rate.')
    if points>int(max_points):
        rate=max(2.0, (int(max_points)-1)/max(duration,1e-12))
        points=int(np.floor(duration*rate))+1
    # A clock is effectively uniform when every interval is within 0.5% of the
    # median and the requested rate matches it within 0.5%.
    dt_tol=max(abs(median_dt)*0.005,1e-12)
    native_uniform=bool(np.max(np.abs(dt-median_dt))<=dt_tol)
    same_rate=abs(rate-inferred_rate)/max(inferred_rate,1e-12)<=0.005
    if native_uniform and same_rate:
        return UniformSignal(t,y,inferred_rate,source_points,False)
    grid=t[0]+np.arange(points,dtype=float)/rate
    grid=grid[grid<=t[-1]+1e-12]
    out=np.interp(grid,t,y)
    return UniformSignal(grid,out,rate,source_points,True)


def _normalized_cutoff(cutoff_hz, nyquist: float, kind: str):
    if kind in {'lowpass','highpass'}:
        c=float(cutoff_hz)
        if not (0<c<nyquist):
            raise ValueError(f'{kind} cutoff must be between 0 and Nyquist ({nyquist:.6g} Hz).')
        return c
    if kind=='bandpass':
        try: lo,hi=[float(x) for x in cutoff_hz]
        except Exception as exc: raise ValueError('Band-pass filter requires low/high cutoff frequencies.') from exc
        if not (0<lo<hi<nyquist):
            raise ValueError(f'Band-pass cutoffs must satisfy 0 < low < high < Nyquist ({nyquist:.6g} Hz).')
        return (lo,hi)
    raise ValueError("Filter kind must be 'lowpass', 'highpass', or 'bandpass'.")


def filter_signal(time_s, values, *, kind: str='lowpass', cutoff_hz=10.0, order: int=4, sample_rate_hz: Optional[float]=None) -> FilterResult:
    """Zero-phase Butterworth filtering on a validated uniform timebase."""
    u=uniform_time_signal(time_s,values,sample_rate_hz=sample_rate_hz)
    key=str(kind).strip().lower().replace('-','')
    aliases={'low':'lowpass','lowpass':'lowpass','high':'highpass','highpass':'highpass','band':'bandpass','bandpass':'bandpass'}
    key=aliases.get(key,key)
    order=int(order)
    if order<1 or order>12:
        raise ValueError('Filter order must be between 1 and 12.')
    nyq=0.5*u.sample_rate_hz
    cutoff=_normalized_cutoff(cutoff_hz,nyq,key)
    sos=signal.butter(order,cutoff,btype={'lowpass':'lowpass','highpass':'highpass','bandpass':'bandpass'}[key],fs=u.sample_rate_hz,output='sos')
    # sosfiltfilt needs enough history; communicate that directly rather than
    # returning a distorted one-pass filter silently.
    if len(u.values)<max(15, 6*order+3):
        raise ValueError('Signal is too short for zero-phase filtering at the selected order.')
    out=signal.sosfiltfilt(sos,u.values)
    ctuple=(float(cutoff),) if np.isscalar(cutoff) else tuple(map(float,cutoff))
    return FilterResult(u.time_s,np.asarray(out,float),u.sample_rate_hz,key,ctuple,order,u.resampled)


def filter_on_original_timebase(time_s, values, *, kind: str='lowpass', cutoff_hz=10.0, order: int=4) -> np.ndarray:
    """Filter through a uniform working grid and interpolate back to source time."""
    original_t=np.asarray(time_s,dtype=float).reshape(-1)
    original_y=np.asarray(values,dtype=float).reshape(-1)
    n=min(len(original_t),len(original_y)); original_t=original_t[:n]; original_y=original_y[:n]
    result=filter_signal(original_t,original_y,kind=kind,cutoff_hz=cutoff_hz,order=order)
    out=np.full(n,np.nan,dtype=float)
    valid=np.isfinite(original_t)
    if valid.any():
        lo=float(result.time_s[0]); hi=float(result.time_s[-1])
        inside=valid&(original_t>=lo)&(original_t<=hi)
        out[inside]=np.interp(original_t[inside],result.time_s,result.values)
    return out


def fft_spectrum(time_s, values, *, max_frequency_hz: Optional[float]=None, sample_rate_hz: Optional[float]=None,
                 window: str='hann', detrend: bool=True) -> SpectrumResult:
    """One-sided amplitude spectrum for telemetry sampled in seconds."""
    u=uniform_time_signal(time_s,values,sample_rate_hz=sample_rate_hz)
    y=np.asarray(u.values,dtype=float)
    if detrend:
        y=signal.detrend(y,type='constant')
    try:
        win=signal.get_window(window,len(y),fftbins=True)
    except Exception as exc:
        raise ValueError(f'Unknown FFT window {window!r}.') from exc
    coherent_gain=float(np.sum(win)/len(win))
    if abs(coherent_gain)<1e-12:
        raise ValueError('FFT window has zero coherent gain.')
    yf=np.fft.rfft(y*win)
    freq=np.fft.rfftfreq(len(y),d=1.0/u.sample_rate_hz)
    amp=(2.0/len(y))*np.abs(yf)/coherent_gain
    if len(amp): amp[0]*=0.5
    if len(y)%2==0 and len(amp)>1: amp[-1]*=0.5
    if max_frequency_hz is not None:
        limit=float(max_frequency_hz)
        if limit<=0: raise ValueError('Maximum FFT frequency must be positive.')
        keep=freq<=limit
        freq=freq[keep]; amp=amp[keep]
    resolution=u.sample_rate_hz/len(y)
    return SpectrumResult(freq,np.asarray(amp,float),u.sample_rate_hz,float(resolution),u.source_points,str(window),bool(detrend))


def rolling_mean(time_s, values, window_s: float) -> np.ndarray:
    t,y,_=_finite_ordered(time_s,values)
    window_s=float(window_s)
    if window_s<=0: raise ValueError('Rolling window must be positive.')
    dt=float(np.median(np.diff(t))); n=max(1,int(round(window_s/dt)))
    kernel=np.ones(n,dtype=float)/n
    return np.convolve(y,kernel,mode='same')


def rolling_rms(time_s, values, window_s: float) -> np.ndarray:
    t,y,_=_finite_ordered(time_s,values)
    window_s=float(window_s)
    if window_s<=0: raise ValueError('Rolling window must be positive.')
    dt=float(np.median(np.diff(t))); n=max(1,int(round(window_s/dt)))
    kernel=np.ones(n,dtype=float)/n
    return np.sqrt(np.maximum(np.convolve(y*y,kernel,mode='same'),0.0))


def power_spectral_density(time_s, values, *, max_frequency_hz: Optional[float]=None, sample_rate_hz: Optional[float]=None,
                           window: str='hann', segment_points: Optional[int]=None, overlap: float=0.5) -> PSDResult:
    """Welch power spectral density for vibration/shake/oscillation analysis."""
    u=uniform_time_signal(time_s,values,sample_rate_hz=sample_rate_hz)
    n=len(u.values)
    seg=int(segment_points or min(4096,max(64,n//8)))
    seg=max(16,min(seg,n))
    overlap=float(overlap)
    if not (0<=overlap<1): raise ValueError('PSD overlap must satisfy 0 <= overlap < 1.')
    noverlap=min(seg-1,int(round(seg*overlap)))
    try:
        freq,density=signal.welch(u.values,fs=u.sample_rate_hz,window=window,nperseg=seg,noverlap=noverlap,detrend='constant',scaling='density')
    except Exception as exc:
        raise ValueError(f'PSD calculation failed: {exc}') from exc
    if max_frequency_hz is not None:
        limit=float(max_frequency_hz)
        if limit<=0: raise ValueError('Maximum PSD frequency must be positive.')
        keep=freq<=limit; freq=freq[keep]; density=density[keep]
    resolution=float(freq[1]-freq[0]) if len(freq)>1 else float('nan')
    return PSDResult(np.asarray(freq,float),np.asarray(density,float),u.sample_rate_hz,resolution,u.source_points,str(window),seg)


def spectrogram(time_s, values, *, max_frequency_hz: Optional[float]=None, sample_rate_hz: Optional[float]=None,
                window: str='hann', segment_points: Optional[int]=None, overlap: float=0.75) -> SpectrogramResult:
    """Time-frequency power map using a common validated telemetry timebase."""
    u=uniform_time_signal(time_s,values,sample_rate_hz=sample_rate_hz)
    n=len(u.values)
    seg=int(segment_points or min(2048,max(64,n//12)))
    seg=max(16,min(seg,n))
    overlap=float(overlap)
    if not (0<=overlap<1): raise ValueError('Spectrogram overlap must satisfy 0 <= overlap < 1.')
    noverlap=min(seg-1,int(round(seg*overlap)))
    freq,t,density=signal.spectrogram(u.values,fs=u.sample_rate_hz,window=window,nperseg=seg,noverlap=noverlap,detrend='constant',scaling='density',mode='psd')
    if max_frequency_hz is not None:
        keep=freq<=float(max_frequency_hz); freq=freq[keep]; density=density[keep,:]
    return SpectrogramResult(np.asarray(freq,float),np.asarray(t+u.time_s[0],float),np.asarray(density,float),u.sample_rate_hz,u.source_points,str(window),seg)
