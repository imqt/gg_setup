#! /bin/bash

set -e

# For parsing json
sudo apt-get install jq
sudo apt-get install python3-pip
pip3 install requests
pip3 install inquirer
pip3 install pyyaml
pip3 install --pre gql[all]

python3 gg_registration.py

# Python sdk:
cd ~
git clone https://github.com/aws/aws-iot-device-sdk-python.git
cd aws-iot-device-sdk-python
python setup.py install
