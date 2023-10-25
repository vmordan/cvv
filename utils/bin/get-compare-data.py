#!/usr/bin/env python3
#
# CVV is a continuous verification visualizer.
# Copyright (c) 2023 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from utils.utils import get_args_parser, Session

parser = get_args_parser('Upload comparison data for 2 last children of a given node.')
parser.add_argument('job',
                    help='Node job identifier or its name (note, it must have at least 2 children for comparison)')
parser.add_argument('-o', '--out', help='File name, in which comparison data json will be saved', required=True)
args = parser.parse_args()

with Session(args) as session:
    job_id_or_name = args.job
    job_id = session.get_comparison_data(job_id_or_name, args.out)
