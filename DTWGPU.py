"""
Provides an interface to CUDA for running a parallel version
of the diagonal DTW algorithm
"""
import pycuda.autoinit
import pycuda.gpuarray as gpuarray
import numpy as np
import matplotlib.pyplot as plt
import time
import scipy.io as sio
import pkg_resources
import sys
from AlignmentTools import *

from pycuda.compiler import SourceModule

DTW_Step_ = None

def getResourceString(filename):
    #If calling from within this directory
    fin = open(filename)
    s = fin.read()
    fin.close()
    return s

def initParallelAlgorithms():
    s = getResourceString("DTWGPU.cu")
    mod = SourceModule(s)
    global DTW_Step_
    DTW_Step_ = mod.get_function("DTW_Diag_Step")

def DTWDiag_GPU(X, Y, k_save = -1, k_stop = -1, box = None, reverse=False, debug=False, dist_fn = getCSMCorresp, stats=None):
    """
    Compute dynamic time warping between two time-ordered
    point clouds in Euclidean space, using CUDA on the back end
    Parameters
    ----------
    X: ndarray(M, d)
        An M-dimensional Euclidean point cloud
    Y: ndarray(N, d)
        An N-dimensional Euclidean point cloud
    k_save: int
        Index of the diagonal d2 at which to save d0, d1, and d2
    k_stop: int
        Index of the diagonal d2 at which to stop computation
    debug: boolean
        Whether to save the accumulated cost matrix
    dist_fn: function: (ndarray(N, d), ndarray(N, d)) -> ndarray(N)
        A function for computing distances between two parallel arrays
    stats: dictionary
        A dictionary for storing information about the computation
    """
    assert(X.shape[1] == Y.shape[1])
    dim = np.array(X.shape[1], dtype=np.int32)
    if not box:
        box = [0, X.shape[0]-1, 0, Y.shape[0]-1]
    M = box[1] - box[0] + 1
    N = box[3] - box[2] + 1

    diagLen = np.array(min(M, N), dtype = np.int32)
    threadsPerBlock = min(diagLen, 512)
    gridSize = int(np.ceil(diagLen/float(threadsPerBlock)))
    threadsPerBlock = np.array(threadsPerBlock, dtype=np.int32)

    d0 = gpuarray.to_gpu(np.zeros(diagLen, dtype=np.float32))
    d1 = gpuarray.to_gpu(np.zeros(diagLen, dtype=np.float32))
    d2 = gpuarray.to_gpu(np.zeros(diagLen, dtype=np.float32))
    csm0 = gpuarray.zeros_like(d0)
    csm1 = gpuarray.zeros_like(d0)
    csm2 = gpuarray.zeros_like(d0)
    if debug:
        U = gpuarray.to_gpu(np.zeros((M, N), dtype=np.float32))
        L = gpuarray.to_gpu(np.zeros((M, N), dtype=np.float32))
        UL = gpuarray.to_gpu(np.zeros((M, N), dtype=np.float32))
        S = gpuarray.to_gpu(np.zeros((M, N), dtype=np.float32))
    else:
        U = gpuarray.to_gpu(np.zeros(1, dtype=np.float32))
        L = gpuarray.to_gpu(np.zeros(1, dtype=np.float32))
        UL = gpuarray.to_gpu(np.zeros(1, dtype=np.float32))
        S = gpuarray.to_gpu(np.zeros(1, dtype=np.float32))

    res = {}
    for k in range(M+N-1):
        DTW_Step_(d0, d1, d2, csm0, csm1, np.array(M, dtype=np.int32), np.array(N, dtype=np.int32), diagLen, np.array(k, dtype=np.int32), np.array(int(debug), dtype=np.int32), U, L, UL, S, block=(int(threadsPerBlock), 1, 1), grid=(gridSize, 1))
        i, j = get_diag_indices(X.shape[0], Y.shape[0], k, box, reverse)
        csm2 = dist_fn(X[i, :], Y[j, :])
        if stats:
            update_alignment_stats(stats, csm2.size)
        if k == k_save:
            res['d0'] = d0.get()
            res['csm0'] = csm0.get()
            res['d1'] = d1.get()
            res['csm1'] = csm1.get()
            res['d2'] = d2.get()
            res['csm2'] = csm2.copy()
        if k == k_stop:
            break
        if k < M+N-2:
            # Rotate buffers
            temp = d0
            d0 = d1
            d1 = d2
            d2 = temp
            csm0 = csm1
            csm1 = gpuarray.to_gpu(csm2)
    res['cost'] = d2.get()[0] + csm2[0]
    if debug:
        res['U'] = U.get()
        res['L'] = L.get()
        res['UL'] = UL.get()
        res['S'] = S.get()
    return res