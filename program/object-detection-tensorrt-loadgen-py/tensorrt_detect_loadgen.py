#!/usr/bin/env python3

import array
import numpy as np
import os
import sys
import time

from coco_helper import (load_image_by_index_and_normalize, image_filenames, original_w_h,
    class_labels, num_classes, bg_class_offset, class_map,
    MODEL_DATA_LAYOUT, MODEL_USE_DLA, BATCH_SIZE)

from tensorrt_helper import (initialize_predictor, inference_for_given_batch)

import mlperf_loadgen as lg


## LoadGen test properties:
#
LOADGEN_SCENARIO        = os.getenv('CK_LOADGEN_SCENARIO', 'SingleStream')
LOADGEN_MODE            = os.getenv('CK_LOADGEN_MODE', 'AccuracyOnly')
LOADGEN_BUFFER_SIZE     = int(os.getenv('CK_LOADGEN_BUFFER_SIZE'))          # set to how many samples are you prepared to keep in memory at once
LOADGEN_DATASET_SIZE    = int(os.getenv('CK_LOADGEN_DATASET_SIZE'))         # set to how many total samples to choose from (0 = full set)
LOADGEN_CONF_FILE       = os.getenv('CK_LOADGEN_CONF_FILE', '')
LOADGEN_MODEL_NAME      = os.getenv('CK_LOADGEN_MODEL_NAME', 'random_model_name')
LOADGEN_COUNT_OVERRIDE  = os.getenv('CK_LOADGEN_COUNT_OVERRIDE', '')        # if not set, use value from LoadGen's config file
LOADGEN_MULTISTREAMNESS = os.getenv('CK_LOADGEN_MULTISTREAMNESS', '')       # if not set, use value from LoadGen's config file

## Model properties:
#
MODEL_MAX_PREDICTIONS   = int(os.getenv('ML_MODEL_MAX_PREDICTIONS', 100))

## Misc
#
VERBOSITY_LEVEL         = int(os.getenv('CK_VERBOSE', '0'))


# Load preprocessed image filepaths:
LOADGEN_DATASET_SIZE = LOADGEN_DATASET_SIZE or len(image_path_list)


def tick(letter, quantity=1):
    print(letter + (str(quantity) if quantity>1 else ''), end='')


# Currently loaded preprocessed images are stored in a dictionary:
preprocessed_image_buffer = {}


def load_query_samples(sample_indices):     # 0-based indices in our whole dataset
    print("load_query_samples({})".format(sample_indices))

    tick('B', len(sample_indices))

    for sample_index in sample_indices:
        img = load_image_by_index_and_normalize(sample_index)

        preprocessed_image_buffer[sample_index] = np.array(img)
        tick('l')
    print('')


def unload_query_samples(sample_indices):
    #print("unload_query_samples({})".format(sample_indices))
    global preprocessed_image_buffer

    preprocessed_image_buffer = {}
    tick('U')
    print('')


def issue_queries(query_samples):

    global BATCH_SIZE 

    if VERBOSITY_LEVEL:
        printable_query = [(qs.index, qs.id) for qs in query_samples]
        print("issue_queries( {} )".format(printable_query))
    tick('Q', len(query_samples))

    for j in range(0, len(query_samples), BATCH_SIZE):
        batch       = query_samples[j:j+BATCH_SIZE]   # NB: the last one may be shorter than BATCH_SIZE in length
        batch_data  = [ preprocessed_image_buffer[qs.index] for qs in batch ]

        trimmed_batch_results, inference_time_s = inference_for_given_batch(batch_data)
        actual_batch_size = len(trimmed_batch_results)

        print("[batch of {}] inference={:.2f} ms".format(actual_batch_size, inference_time_s*1000))

        tick('p', len(batch))
        if VERBOSITY_LEVEL:
            print("predicted_batch_results = {}".format(trimmed_batch_results))

        response = []
        response_array_refs = []    # This is needed to guarantee that the individual buffers to which we keep extra-Pythonian references, do not get garbage-collected.
        for qs, all_boxes_for_this_sample in zip(batch, trimmed_batch_results):

            num_active_boxes_for_this_sample = all_boxes_for_this_sample[MODEL_MAX_PREDICTIONS*7].view('int32')
            global_image_index = qs.index
            width_orig, height_orig = original_w_h[global_image_index]
            reformed_active_boxes_for_this_sample = []
            for i in range(num_active_boxes_for_this_sample):
                (image_id, ymin, xmin, ymax, xmax, confidence_score, class_number) = all_boxes_for_this_sample[i*7:(i+1)*7]

                if class_map:
                    class_number = float(class_map[int(class_number)])

                reformed_active_boxes_for_this_sample += [
                    float(global_image_index), ymin, xmin, ymax, xmax, confidence_score, class_number ]

            response_array = array.array("B", np.array(reformed_active_boxes_for_this_sample, np.float32).tobytes())
            response_array_refs.append(response_array)
            bi = response_array.buffer_info()
            response.append(lg.QuerySampleResponse(qs.id, bi[0], bi[1]))
        lg.QuerySamplesComplete(response)
        #tick('R', len(response))
    sys.stdout.flush()


def flush_queries():
    pass


def process_latencies(latencies_ns):
    print("LG called process_latencies({})".format(latencies_ns))

    latencies_size      = len(latencies_ns)
    latencies_avg       = int(sum(latencies_ns)/latencies_size)
    latencies_sorted    = sorted(latencies_ns)
    latencies_p50       = int(latencies_size * 0.5);
    latencies_p90       = int(latencies_size * 0.9);

    print("--------------------------------------------------------------------")
    print("|                LATENCIES (in nanoseconds and fps)                |")
    print("--------------------------------------------------------------------")
    print("Number of queries run:       {:9d}".format(latencies_size))
    print("Min latency:                 {:9d} ns   ({:.3f} fps)".format(latencies_sorted[0], 1e9/latencies_sorted[0]))
    print("Median latency:              {:9d} ns   ({:.3f} fps)".format(latencies_sorted[latencies_p50], 1e9/latencies_sorted[latencies_p50]))
    print("Average latency:             {:9d} ns   ({:.3f} fps)".format(latencies_avg, 1e9/latencies_avg))
    print("90 percentile latency:       {:9d} ns   ({:.3f} fps)".format(latencies_sorted[latencies_p90], 1e9/latencies_sorted[latencies_p90]))
    print("Max latency:                 {:9d} ns   ({:.3f} fps)".format(latencies_sorted[-1], 1e9/latencies_sorted[-1]))
    print("--------------------------------------------------------------------")


def benchmark_using_loadgen():
    "Perform the benchmark using python API for the LoadGen library"

    pycuda_context, max_batch_size, input_volume, output_volume, num_layers = initialize_predictor()

    scenario = {
        'SingleStream':     lg.TestScenario.SingleStream,
        'MultiStream':      lg.TestScenario.MultiStream,
        'Server':           lg.TestScenario.Server,
        'Offline':          lg.TestScenario.Offline,
    }[LOADGEN_SCENARIO]

    mode = {
        'AccuracyOnly':     lg.TestMode.AccuracyOnly,
        'PerformanceOnly':  lg.TestMode.PerformanceOnly,
        'SubmissionRun':    lg.TestMode.SubmissionRun,
    }[LOADGEN_MODE]

    ts = lg.TestSettings()
    if LOADGEN_CONF_FILE:
        ts.FromConfig(LOADGEN_CONF_FILE, LOADGEN_MODEL_NAME, LOADGEN_SCENARIO)
    ts.scenario = scenario
    ts.mode     = mode

    if LOADGEN_MULTISTREAMNESS:
        ts.multi_stream_samples_per_query = int(LOADGEN_MULTISTREAMNESS)

    if LOADGEN_COUNT_OVERRIDE:
        ts.min_query_count = int(LOADGEN_COUNT_OVERRIDE)
        ts.max_query_count = int(LOADGEN_COUNT_OVERRIDE)

    sut = lg.ConstructSUT(issue_queries, flush_queries, process_latencies)
    qsl = lg.ConstructQSL(LOADGEN_DATASET_SIZE, LOADGEN_BUFFER_SIZE, load_query_samples, unload_query_samples)

    log_settings = lg.LogSettings()
    log_settings.enable_trace = False
    lg.StartTestWithLogSettings(sut, qsl, ts, log_settings)

    lg.DestroyQSL(qsl)
    lg.DestroySUT(sut)
    pycuda_context.pop()


try:
    benchmark_using_loadgen()
except Exception as e:
    print('{}'.format(e))
