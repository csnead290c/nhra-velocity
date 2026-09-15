from __future__ import annotations

"""Binned 2-D load/mixture/occupancy maps for telemetry analysis."""

from dataclasses import dataclass
from typing import Any
import numpy as np
from scipy import stats


@dataclass
class BinnedMapResult:
    x_edges: np.ndarray
    y_edges: np.ndarray
    values: np.ndarray
    counts: np.ndarray
    statistic: str
    source_points: int
    used_points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "source_points": self.source_points,
            "used_points": self.used_points,
            "shape": list(self.values.shape),
        }


def binned_map(x, y, z=None, *, bins=(30, 30), statistic: str="mean", mask=None, range=None) -> BinnedMapResult:
    xx=np.asarray(x,dtype=float).reshape(-1); yy=np.asarray(y,dtype=float).reshape(-1)
    n=min(len(xx),len(yy)); xx=xx[:n]; yy=yy[:n]
    zz=None
    if z is not None:
        zz=np.asarray(z,dtype=float).reshape(-1)[:n]
        n=min(n,len(zz)); xx=xx[:n]; yy=yy[:n]; zz=zz[:n]
    good=np.isfinite(xx)&np.isfinite(yy)
    if zz is not None: good &= np.isfinite(zz)
    if mask is not None:
        mm=np.asarray(mask,dtype=bool).reshape(-1)[:n]
        if len(mm)<n:
            raise ValueError('Binned-map mask length does not match source arrays.')
        good &= mm
    xx=xx[good]; yy=yy[good]
    if zz is not None: zz=zz[good]
    if len(xx)<2:
        raise ValueError('Binned map requires at least two finite samples.')
    key=str(statistic or 'mean').strip().lower()
    if key=='count':
        values,xedges,yedges=np.histogram2d(xx,yy,bins=bins,range=range)
        counts=values.copy()
    else:
        if zz is None:
            raise ValueError(f'{key} binned map requires a Z/value channel.')
        allowed={'mean','median','min','max','std','sum'}
        if key not in allowed:
            raise ValueError(f'Unsupported binned-map statistic: {statistic!r}')
        values,xedges,yedges,_=stats.binned_statistic_2d(xx,yy,zz,statistic=key,bins=bins,range=range)
        counts,_,_=np.histogram2d(xx,yy,bins=[xedges,yedges])
    return BinnedMapResult(np.asarray(xedges,float),np.asarray(yedges,float),np.asarray(values,float),np.asarray(counts,float),key,n,int(len(xx)))
