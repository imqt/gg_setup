#! /bin/bash

set -e

# For parsing json
sudo apt-get install jq
sudo apt-get install python3-pip

pip install requests
pip install inquirer
pip install pyyaml
pip install --pre gql[all]

python3 gg_registration.py

# Python sdk:
cd ~
git clone https://github.com/aws/aws-iot-device-sdk-python.git
cd aws-iot-device-sdk-python
sudo python setup.py install
