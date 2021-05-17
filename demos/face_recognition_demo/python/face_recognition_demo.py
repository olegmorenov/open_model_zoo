#!/usr/bin/env python3
"""
 Copyright (c) 2018-2021 Intel Corporation

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

import logging as log
import os.path as osp
import sys
from time import perf_counter
from argparse import ArgumentParser
from pathlib import Path

import cv2
import numpy as np

from ie_module import InferenceContext
from landmarks_detector import LandmarksDetector
from face_detector import FaceDetector
from faces_database import FacesDatabase
from face_identifier import FaceIdentifier

sys.path.append(osp.join(osp.dirname(osp.dirname(osp.dirname(osp.abspath(__file__)))), 'common/python'))

import monitors
from helpers import resolution
from images_capture import open_images_capture
from models import OutputTransform
from performance_metrics import PerformanceMetrics


DEVICE_KINDS = ['CPU', 'GPU', 'FPGA', 'MYRIAD', 'HETERO', 'HDDL']


def build_argparser():
    parser = ArgumentParser()

    general = parser.add_argument_group('General')
    general.add_argument('-i', '--input', required=True,
                         help='Required. An input to process. The input must be a single image, '
                              'a folder of images, video file or camera id.')
    general.add_argument('--loop', default=False, action='store_true',
                         help='Optional. Enable reading the input in a loop.')
    general.add_argument('-o', '--output',
                         help='Optional. Name of output to save.')
    general.add_argument('-limit', '--output_limit', default=1000, type=int,
                         help='Optional. Number of frames to store in output. '
                              'If 0 is set, all frames are stored.')
    general.add_argument('--output_resolution', default=None, type=resolution,
                         help='Optional. Specify the maximum output window resolution '
                              'in (width x height) format. Example: 1280x720. '
                              'Input frame size used by default.')
    general.add_argument('--no_show', action='store_true',
                         help="Optional. Don't show output.")
    general.add_argument('-cw', '--crop_width', default=0, type=int,
                         help='Optional. Crop the input stream to this width. '
                              'Both -cw and -ch parameters should be specified '
                              'to use crop.')
    general.add_argument('-ch', '--crop_height', default=0, type=int,
                         help='Optional. Crop the input stream to this height. '
                              'Both -cw and -ch parameters should be specified '
                              'to use crop.')
    general.add_argument('--match_algo', default='HUNGARIAN', choices=('HUNGARIAN', 'MIN_DIST'),
                         help='Optional. Algorithm for face matching. Default: HUNGARIAN.')
    general.add_argument('-u', '--utilization_monitors', default='', type=str,
                         help='Optional. List of monitors to show initially.')

    gallery = parser.add_argument_group('Faces database')
    gallery.add_argument('-fg', type=Path, required=True,
                         help='Required. Path to the face images directory.')
    gallery.add_argument('--run_detector', action='store_true',
                         help='Optional. Use Face Detection model to find faces '
                              'on the face images, otherwise use full images.')
    gallery.add_argument('--allow_grow', action='store_true',
                         help='Optional. Allow to grow faces gallery and to dump on disk. '
                               'Available only if --no_show option is off.')

    models = parser.add_argument_group('Models')
    models.add_argument('-m_fd', type=Path, required=True,
                        help='Required. Path to an .xml file with Face Detection model.')
    models.add_argument('-m_lm', type=Path, required=True,
                        help='Required. Path to an .xml file with Facial Landmarks Detection model.')
    models.add_argument('-m_reid', type=Path, required=True,
                        help='Required. Path to an .xml file with Face Reidentification model.')
    models.add_argument('-fd_iw', '--fd_input_width', default=0, type=int,
                         help='Optional. Specify the input width of detection model. '
                              'Both -fd_iw and -fd_ih parameters should be specified '
                              'for reshape.')
    models.add_argument('-fd_ih', '--fd_input_height', default=0, type=int,
                         help='Optional. Specify the input height of detection model. '
                              'Both -fd_iw and -fd_ih parameters should be specified '
                              'for reshape.')

    infer = parser.add_argument_group('Inference options')
    infer.add_argument('-d_fd', default='CPU', choices=DEVICE_KINDS,
                       help='Optional. Target device for Face Detection model. '
                            'Default value is CPU.')
    infer.add_argument('-d_lm', default='CPU', choices=DEVICE_KINDS,
                       help='Optional. Target device for Facial Landmarks Detection '
                            'model. Default value is CPU.')
    infer.add_argument('-d_reid', default='CPU', choices=DEVICE_KINDS,
                       help='Optional. Target device for Face Reidentification '
                            'model. Default value is CPU.')
    infer.add_argument('-l', '--cpu_lib', metavar="PATH", default='',
                       help='Optional. For MKLDNN (CPU)-targeted custom layers, '
                            'if any. Path to a shared library with custom '
                            'layers implementations.')
    infer.add_argument('-c', '--gpu_lib', metavar="PATH", default='',
                       help='Optional. For clDNN (GPU)-targeted custom layers, '
                            'if any. Path to the XML file with descriptions '
                            'of the kernels.')
    infer.add_argument('-v', '--verbose', action='store_true',
                       help='Optional. Be more verbose.')
    infer.add_argument('-pc', '--perf_stats', action='store_true',
                       help='Optional. Output detailed per-layer performance stats.')
    infer.add_argument('-t_fd', metavar='[0..1]', type=float, default=0.6,
                       help='Optional. Probability threshold for face detections.')
    infer.add_argument('-t_id', metavar='[0..1]', type=float, default=0.3,
                       help='Optional. Cosine distance threshold between two vectors '
                            'for face identification.')
    infer.add_argument('-exp_r_fd', metavar='NUMBER', type=float, default=1.15,
                       help='Optional. Scaling ratio for bboxes passed to face recognition.')
    return parser


class FrameProcessor:
    QUEUE_SIZE = 16

    def __init__(self, args):
        used_devices = {args.d_fd, args.d_lm, args.d_reid}
        self.context = InferenceContext(used_devices, args.cpu_lib, args.gpu_lib, args.perf_stats)
        context = self.context

        log.info("Loading models")
        face_detector_net = self.load_model(args.m_fd)

        assert (args.fd_input_height and args.fd_input_width) or \
               (args.fd_input_height == 0 and args.fd_input_width == 0), \
            "Both -fd_iw and -fd_ih parameters should be specified for reshape"

        if args.fd_input_height and args.fd_input_width :
            face_detector_net.reshape({"data": [1, 3, args.fd_input_height, args.fd_input_width]})
        landmarks_net = self.load_model(args.m_lm)
        face_reid_net = self.load_model(args.m_reid)

        self.face_detector = FaceDetector(face_detector_net,
                                          confidence_threshold=args.t_fd,
                                          roi_scale_factor=args.exp_r_fd)

        self.landmarks_detector = LandmarksDetector(landmarks_net)
        self.face_identifier = FaceIdentifier(face_reid_net,
                                              match_threshold=args.t_id,
                                              match_algo = args.match_algo)

        self.face_detector.deploy(args.d_fd, context)
        self.landmarks_detector.deploy(args.d_lm, context,
                                       queue_size=self.QUEUE_SIZE)
        self.face_identifier.deploy(args.d_reid, context,
                                    queue_size=self.QUEUE_SIZE)
        log.info("Models are loaded")

        log.info("Building faces database using images from '%s'" % (args.fg))
        self.faces_database = FacesDatabase(args.fg, self.face_identifier,
                                            self.landmarks_detector,
                                            self.face_detector if args.run_detector else None, args.no_show)
        self.face_identifier.set_faces_database(self.faces_database)
        log.info("Database is built, registered %s identities" % (len(self.faces_database)))

        self.allow_grow = args.allow_grow and not args.no_show

    def load_model(self, model_path):
        model_path = osp.abspath(model_path)
        model_weights_path = osp.splitext(model_path)[0] + ".bin"
        log.info("Loading the model from '%s'" % (model_path))
        assert osp.isfile(model_path), \
            "Model description is not found at '%s'" % (model_path)
        assert osp.isfile(model_weights_path), \
            "Model weights are not found at '%s'" % (model_weights_path)
        model = self.context.ie_core.read_network(model_path, model_weights_path)
        log.info("Model is loaded")
        return model

    def process(self, frame):
        assert len(frame.shape) == 3, \
            "Expected input frame in (H, W, C) format"
        assert frame.shape[2] in [3, 4], \
            "Expected BGR or BGRA input"

        orig_image = frame.copy()
        frame = frame.transpose((2, 0, 1)) # HWC to CHW
        frame = np.expand_dims(frame, axis=0)

        self.face_detector.clear()
        self.landmarks_detector.clear()
        self.face_identifier.clear()

        self.face_detector.start_async(frame)
        rois = self.face_detector.get_roi_proposals(frame)
        if self.QUEUE_SIZE < len(rois):
            log.warning("Too many faces for processing. Will be processed only %s of %s." %
                (self.QUEUE_SIZE, len(rois)))
            rois = rois[:self.QUEUE_SIZE]
        self.landmarks_detector.start_async(frame, rois)
        landmarks = self.landmarks_detector.get_landmarks()

        self.face_identifier.start_async(frame, rois, landmarks)
        face_identities, unknowns = self.face_identifier.get_matches()
        if self.allow_grow and len(unknowns) > 0:
            for i in unknowns:
                # This check is preventing asking to save half-images in the boundary of images
                if rois[i].position[0] == 0.0 or rois[i].position[1] == 0.0 or \
                    (rois[i].position[0] + rois[i].size[0] > orig_image.shape[1]) or \
                    (rois[i].position[1] + rois[i].size[1] > orig_image.shape[0]):
                    continue
                crop = orig_image[int(rois[i].position[1]):int(rois[i].position[1]+rois[i].size[1]), int(rois[i].position[0]):int(rois[i].position[0]+rois[i].size[0])]
                name = self.faces_database.ask_to_save(crop)
                if name:
                    id = self.faces_database.dump_faces(crop, face_identities[i].descriptor, name)
                    face_identities[i].id = id

        outputs = [rois, landmarks, face_identities]

        return outputs

    def get_performance_stats(self):
        stats = {
            'face_detector': self.face_detector.get_performance_stats(),
            'landmarks': self.landmarks_detector.get_performance_stats(),
            'face_identifier': self.face_identifier.get_performance_stats(),
        }
        return stats


def draw_detections(frame, frame_processor, detections, output_transform):
    size = frame.shape[:2]
    frame = output_transform.resize(frame)
    for roi, landmarks, identity in zip(*detections):
        text = frame_processor.face_identifier.get_identity_label(identity.id)
        if identity.id != FaceIdentifier.UNKNOWN_ID:
            text += ' %.2f%%' % (100.0 * (1 - identity.distance))

        xmin = max(int(roi.position[0]), 0)
        ymin = max(int(roi.position[1]), 0)
        xmax = min(int(roi.position[0] + roi.size[0]), size[1])
        ymax = min(int(roi.position[1] + roi.size[1]), size[0])
        xmin, ymin, xmax, ymax = output_transform.scale([xmin, ymin, xmax, ymax])
        cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (0, 220, 0), 2)

        keypoints = [landmarks.left_eye, landmarks.right_eye, landmarks.nose_tip,
                     landmarks.left_lip_corner, landmarks.right_lip_corner]
        for point in keypoints:
            x = xmin + output_transform.scale(roi.size[0] * point[0])
            y = ymin + output_transform.scale(roi.size[1] * point[1])
            cv2.circle(frame, (int(x), int(y)), 2, (0, 255, 255), 2)
        textsize = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 1)[0]
        cv2.rectangle(frame, (xmin, ymin), (xmin + textsize[0], ymin - textsize[1]), (255, 255, 255), cv2.FILLED)
        cv2.putText(frame, text, (xmin, ymin), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1)

    return frame

def center_crop(frame, crop_size):
    fh, fw, _ = frame.shape
    crop_size[0], crop_size[1] = min(fw, crop_size[0]), min(fh, crop_size[1])
    return frame[(fh - crop_size[1]) // 2 : (fh + crop_size[1]) // 2,
                 (fw - crop_size[0]) // 2 : (fw + crop_size[0]) // 2,
                 :]

def main():
    args = build_argparser().parse_args()

    log.basicConfig(format="[ %(levelname)s ] %(asctime)-15s %(message)s",
                    level=log.INFO if not args.verbose else log.DEBUG, stream=sys.stdout)

    cap = open_images_capture(args.input, args.loop)
    frame_processor = FrameProcessor(args)

    log.info('Starting inference...')
    print("To close the application, press 'CTRL+C' here or switch to the output window and press ESC key")

    frame_num = 0
    metrics = PerformanceMetrics()
    print_perf_stats = args.perf_stats
    presenter = None
    output_transform = None
    input_crop = None
    if args.crop_width and args.crop_height:
        input_crop = np.array((args.crop_width, args.crop_height))
    video_writer = cv2.VideoWriter()

    while True:
        start_time = perf_counter()
        frame = cap.read()
        if frame is None:
            if frame_num == 0:
                raise ValueError("Can't read an image from the input")
            break
        if input_crop is not None:
            frame = center_crop(frame, input_crop)
        if frame_num == 0:
            output_transform = OutputTransform(frame.shape[:2], args.output_resolution)
            if args.output_resolution:
                output_resolution = output_transform.new_resolution
            else:
                output_resolution = (frame.shape[1], frame.shape[0])
            presenter = monitors.Presenter(args.utilization_monitors, 55,
                                           (round(output_resolution[0] / 4), round(output_resolution[1] / 8)))
            if args.output and not video_writer.open(args.output, cv2.VideoWriter_fourcc(*'MJPG'),
                                                     cap.fps(), output_resolution):
                raise RuntimeError("Can't open video writer")

        detections = frame_processor.process(frame)
        presenter.drawGraphs(frame)
        frame = draw_detections(frame, frame_processor, detections, output_transform)
        metrics.update(start_time, frame)

        frame_num += 1
        if video_writer.isOpened() and (args.output_limit <= 0 or frame_num <= args.output_limit):
            video_writer.write(frame)

        if print_perf_stats:
            log.info('Performance stats:')
            log.info(frame_processor.get_performance_stats())
        if not args.no_show:
            cv2.imshow('Face recognition demo', frame)
            key = cv2.waitKey(1)
            # Quit
            if key in {ord('q'), ord('Q'), 27}:
                break
            presenter.handleKey(key)


    metrics.print_total()
    print(presenter.reportMeans())


if __name__ == '__main__':
    sys.exit(main() or 0)
