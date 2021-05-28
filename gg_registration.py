import os
import zipfile
import json
import requests
import inquirer
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport

AWS_CONFIG_FOLDER="/home/pi/.aws/"
AWS_GREENGRASS_FOLDER="/greengrass" # TODO:update code to use this variable

theme_file = open(os.getcwd()+"/inquirerTheme.json")
inquirer_theme=inquirer.themes.load_theme_from_dict(json.load(theme_file))

# Select your transport with a defined url endpoint
transport = AIOHTTPTransport(
    url="https://e6g65yezbvempgzshak2xptr4m.appsync-api.us-west-1.amazonaws.com/graphql",
    headers={'x-api-key': 'da2-f7xd76bia5fhtbrwkp4sjtrshe'}
)

# Create a GraphQL client using the defined transport
client = Client(transport=transport, fetch_schema_from_transport=True)

putDevice = gql(
    """
    mutation ($iot_name:String!, $edge_device_id: ID) {
        putDevice (
            edge_device_id: $edge_device_id,
            iot_name: $iot_name, 
            name: $iot_name,
        ) {
            id
        }
    }
"""
)

putSensor = gql(
    """
    mutation (
        $sensor_name          : String!,
        $device_id            : ID!,
        $sensor_type_id       : ID!,
        $driver_id            : ID!,
        $metric_ids          : [ID!]!
        ) {
        putSensor(
            name           : $sensor_name,
            device_id      : $device_id,
            sensor_type_id : $sensor_type_id, 
            driver_id      : $driver_id,
            metric_ids     : $metric_ids
        ) {
            name
            device_id
            sensor_type_id
            driver_id
            metrics {
                id
                name
                unit
            }
        }
    }
"""
)

getSensorTypes = gql(
    """
    {
        getSensorTypes {
            id
            model
            metrics {
                id
                name
                unit
            }
            drivers {
                id
                uri
            }
        }
    }
"""
)

putEdge = gql(
    """
    mutation ($iot_name:String!) {
        putDevice (
            iot_name: $iot_name, 
            name: $iot_name, 
        ) {
            id
        }
    }
"""
)

############################################# IoT Thing
def create_iot_thing(thing_name):
    """
    Note: 
    1. Once a thing is created, you cannot change its name (aws iot rule)

    2. Currently, a new IoT thing is getting the 
    All_Available policy on creation for development convenience TODO: should change to a stricter policy
    """
    print("Creating IoT Thing with name: " + thing_name)
    # thing_name = input("Enter a new device name: ")
    ret = os.system("aws iot create-thing --thing-name " + thing_name
        + " > /tmp/create-thing-response")
    print("Success" if ret == 0 else "Failed", ": create-thing")

    # Get thingArn to return
    ctr = open("/tmp/create-thing-response")
    thing_data = json.load(ctr)
    thing_arn = thing_data["thingArn"]

    # Create and attach certificate to thing
    cert_data = create_keys_n_cert(thing_name)
    certificate_arn = cert_data["certificateArn"]
    ret = os.system("aws iot attach-thing-principal"
    + " --thing-name " + thing_name 
    + " --principal " + certificate_arn)
    print("Success" if ret == 0 else "Failed", ": attach-thing-principal (certificate)")
    
    # Attach policy to thing
    policy_name = "All_Available"
    ret = os.system("aws iot attach-policy"
    + " --target " + certificate_arn
    + " --policy-name " + policy_name)
    print("Success" if ret == 0 else "Failed", ": attach-policy (policy)")
    
    return {"thingName" : thing_name, "thingArn":thing_arn, "certificateArn": certificate_arn}

def create_keys_n_cert(thing_name):
    # Note: https://aws.amazon.com/blogs/iot/understanding-the-aws-iot-security-model/
    os.mkdir(os.getcwd() + "/" + thing_name)
    thing_name = os.getcwd() + "/" + thing_name + "/" + thing_name
    ret = os.system(
        "aws iot create-keys-and-certificate --set-as-active" 
        + " --public-key-outfile "  + thing_name +".public.key" 
        + " --private-key-outfile " + thing_name +".private.key" 
        + " --certificate-pem-outfile " + thing_name +".cert.pem" 
        + " > /tmp/create-keys-and-certificate-response"
        )
    print("Success" if ret == 0 else "Failed", ": create-keys-and-certificate")
    ckncr = open("/tmp/create-keys-and-certificate-response")
    cert_data = json.load(ckncr)
    # Pretty Printing JSON string back
    # print(json.dumps(cert_data, indent = 4, sort_keys=True))
    return cert_data

############################################ Greengrass
def create_greengrass_group(group_name):
    ret = os.system("aws greengrass create-group"
        + " --name " + group_name
        + " > /tmp/create-group-response"
    )
    print("Success" if ret == 0 else "Failed", ":  create-group")

    cgr = open("/tmp/create-group-response")
    group_data = json.load(cgr)

    core_data = create_iot_thing(group_name+"_Core")
    
    core_def_ver_data = create_core_definition(core_data, group_name)
 
    # Update DB with new info
    # Send core name to DB
    ret_val = client.execute(putEdge, variable_values={"iot_name":core_data["thingName"]})
    edge_device_id = ret_val["putDevice"]["id"]

    devices_list = create_things(group_name, edge_device_id)
    device_def_ver_data = create_device_definition(devices_list, group_name)
    
    sub_def_ver_data = create_subscription_definition(devices_list, group_name)

    group_version_data = {
        "groupId": group_data["Id"],
        "coreDefVerArn": core_def_ver_data["LatestVersionArn"],
        "subDefVerArn": sub_def_ver_data["LatestVersionArn"],
        "devDefVerArn": device_def_ver_data["LatestVersionArn"]
    }

    create_group_version(group_version_data)

    ret = os.system("aws greengrass get-group"
        + " --group-id " + group_data["Id"]
        + " > /tmp/get-group-response"
    )
    print("Success" if ret == 0 else "Failed", ": greengrass get-group")
    ggr = open("/tmp/get-group-response")
    group_data = json.load(ggr)
    ggr.close()

    # Move certs into /greengrass/certs
    ret = os.system("sudo cp ./" + group_name + "_Core" + "/" + group_name+"_Core.public.key" + " /greengrass/certs/core.public.key")
    print("Success" if ret == 0 else "Failed", ": copied public key into /greengrass/certs")
    
    ret = os.system("sudo cp ./" + group_name + "_Core" + "/" + group_name+"_Core.private.key" + " /greengrass/certs/core.private.key")
    print("Success" if ret == 0 else "Failed", ": copied private key into /greengrass/certs")
   
    ret = os.system("sudo cp ./" + group_name + "_Core" + "/" + group_name+"_Core.cert.pem" + " /greengrass/certs/core.cert.pem")
    print("Success" if ret == 0 else "Failed", ": copied certificate into /greengrass/certs")

    ret = os.system("sudo wget https://www.amazontrust.com/repository/AmazonRootCA1.pem -O /greengrass/certs/root.ca.pem")
    print("Success" if ret == 0 else "Failed", ": downloaded root ca pem /greengrass/certs")
    
    # Update /greengrass/config/config.json
    update_config_json(core_data["thingArn"])

    ret = os.system("sudo cp config.json /greengrass/config/config.json")
    print("Success" if ret == 0 else "Failed", ": config.json moved to /greengrass/config")

    # Start core
    ret = os.system("sudo /greengrass/ggc/core/./greengrassd start")
    print("Success" if ret == 0 else "Failed", ": greengrass core started")

    create_deployment(group_data)
    
    return group_version_data

def create_deployment(group_data):

    ret = os.system("aws greengrass create-deployment"
        + " --deployment-type NewDeployment"
        + " --group-id " + group_data["Id"]
        + " --group-version-id " + group_data["LatestVersion"]
    )
    print("Success" if ret == 0 else "Failed", ": create-deployment")

def create_core_definition(device_data, group_name):

    formatted_string_command = 'aws greengrass create-core-definition'\
    + ' --name ' + '"' + group_name + '_Cores"'\
    + ' --initial-version ' \
    + '"{\\"Cores\\":[{\\"Id\\":' + '\\"' + device_data["thingName"] + '\\"'\
    + ',\\"ThingArn\\":' + '\\"' + device_data["thingArn"] + '\\"'\
    + ',\\"CertificateArn\\":' + '\\"' + device_data["certificateArn"] + '\\"'\
    + ',\\"SyncShadow\\":true}]}"'\
    + ' > /tmp/create-core-def-response'

    print(formatted_string_command)
    ret = os.system(formatted_string_command)
    print("Success" if ret == 0 else "Failed", ": create-core-definition")
    ccdr = open("/tmp/create-core-def-response")

    return json.load(ccdr)

def update_config_json(coreArn):
    config = {}
    with open("config.json", "r") as config_file:
        config = json.load(config_file)

        config["coreThing"]["thingArn"] = coreArn

        # ret = os.system("aws iot describe-endpoint > /tmp/iot-endpoint")
        # der = open("/tmp/iot-endpoint")
        # endpoint_address = json.load(der)["endpointAddress"]
        # der.close()

        # config["coreThing"]["iotHost"] = endpoint_address

    with open("config.json", "w") as config_file:
        config_file.write(json.dumps(config, indent=4))

    return

def create_things(group_name, edge_device_id):
    devices_names = []

    while True:
        device_count = inquirer.text("How many devices do you have for this group")
        try:
            device_count = int(device_count)
        except:
            print("You must enter a number")
            continue
        
        print("Default device name(s) for " + group_name + " group: " + group_name + "_D1, " + group_name + "_D2, " + group_name + "_D3, ...")
        c = inquirer.list_input("Use default name(s)", choices=["Yes", "No"])
        if c == "Yes":
            for device_number in range(device_count):
                devices_names.append(group_name + "_D" + str(device_number + 1))
        else:
            for device_number in range(device_count):
                devices_names.append(inquirer.text("Please provide device " + str(device_number + 1) + "'s name"))
        
        c = confirm_answer(devices_names)
        if c == "Redo":
            devices_names.clear()
            continue
        break

    devices_list = []
    for device_name in devices_names:
        device_data = create_iot_thing(device_name)
        devices_list.append(
            {
                "name" : device_name,
                "thingArn" : device_data["thingArn"],
                "certificateArn" : device_data["certificateArn"]
            }
        )

    # Send device name to DB
    device_id = client.execute(putDevice, variable_values={"iot_name":device_name, "edge_device_id":edge_device_id})["putDevice"]["id"]
    configure_sensor_per_device(device_id, device_name)

    return devices_list

def create_device_definition(devices_list, group_name):
    formatted_list_str = ''
    for device in devices_list:
        extra = '{\\"Id\\":' + '\\"' + device["name"] + '\\"' \
        + ',\\"ThingArn\\":' + '\\"' + device["thingArn"] + '\\"'\
        + ',\\"CertificateArn\\":' + '\\"' + device["certificateArn"] + '\\"'\
        + ',\\"SyncShadow\\":true},'
        formatted_list_str += extra
    formatted_list_str=formatted_list_str[:-1]
    print(formatted_list_str)
    ret = os.system('aws greengrass create-device-definition'
        + ' --name ' + '"' + group_name + '_Devices"'
        + ' --initial-version ' 
        + '"{\\"Devices\\":[' + formatted_list_str + ']}"'
        + ' > /tmp/create-device-def-response'
    )
    print("Success" if ret == 0 else "Failed", ": create-device-definition")
    cddr = open("/tmp/create-device-def-response")
    return json.load(cddr)

def create_subscription_definition(devices_list, group_name):
    formatted_list_str = ''
    for device in devices_list:
        extra = '{\\"Id\\":' + '\\"' + device["name"] + '_to_cloud' + '\\"' \
        + ',\\"Source\\":' + '\\"' + device["thingArn"] + '\\"'\
        + ',\\"Subject\\":' + '\\"readings\\"'\
        + ',\\"Target\\":\\"cloud\\"},'
        formatted_list_str += extra
    formatted_list_str=formatted_list_str[:-1]
    print(formatted_list_str)
    ret = os.system('aws greengrass create-subscription-definition'
        + ' --name ' + '"' + group_name + '_Subscriptions"'
        + ' --initial-version ' 
        + '"{\\"Subscriptions\\":[' + formatted_list_str + ']}"'
        + ' > /tmp/create-subscription-def-response'
    )
    print("Success" if ret == 0 else "Failed", ": create-subscription-definition")
    cddr = open("/tmp/create-subscription-def-response")
    return json.load(cddr)

def create_group_version(group_version_data):

    core_def_ver_arn = "" \
        if   group_version_data["coreDefVerArn"] == "" \
        else " --core-definition-version-arn " + group_version_data["coreDefVerArn"]

    device_def_ver_arn = "" \
        if   group_version_data["devDefVerArn"] == "" \
        else " --device-definition-version-arn " + group_version_data["devDefVerArn"]

    sub_def_ver_arn = "" \
        if   group_version_data["subDefVerArn"] == "" \
        else " --subscription-definition-version-arn " + group_version_data["subDefVerArn"]

    ret = os.system("aws greengrass create-group-version" 
        + " --group-id " + group_version_data["groupId"]
        + core_def_ver_arn
        + device_def_ver_arn
        + sub_def_ver_arn
    )
    print("Success" if ret == 0 else "Failed", ": create-group-version")
    return

############################################### GraphQL
def configure_sensor_per_device(device_id, device_name):

    sensorTypes = client.execute(getSensorTypes)["getSensorTypes"]
    sensorModels = [st["model"] for st in sensorTypes]

    selected_sensors = inquirer.prompt([
        inquirer.Checkbox('a',
            message="Which sensor(s) do you have on your end device? ",
            choices=sensorModels,
        )
    ], theme=inquirer_theme)['a']
    confirm_answer(selected_sensors)

    selected_metrics = []
    sensor_count = 1
    for sensor in [sensorTypes[sensorModels.index(s)] for s in selected_sensors]:
        temp_selected_metrics = inquirer.prompt([
            inquirer.Checkbox('a',
                message="Metric(s) on sensor " + sensor["model"] 
                + " with ID: " + sensor["id"],
                choices=[m["id"] + " Name: " + m["name"] + " | Unit: " + m["unit"] 
                for m in sensor["metrics"] if m["id"] not in selected_metrics],
            )
        ], theme=inquirer_theme)['a']
        
        for metric in temp_selected_metrics:
            selected_metrics.append(metric[0])

        putSensorResult = client.execute(putSensor
        , variable_values={
            "sensor_name"          : device_name+"_s" + str(sensor_count),
            "device_id"            : device_id,
            "sensor_type_id"       : sensor["id"],
            "driver_id"            : sensor["drivers"][0]["id"],
            "metric_ids"          : [int(m[0]) for m in temp_selected_metrics]
        })

        print("putSensor result: " + str(putSensorResult["putSensor"]))
        sensor_count += 1

################################################## Main
def main():
    # Things to always do:
    install_AWS_CLI()
    configure_aws_access()
    configure_aws_access_user_input()
    setup_greengrass_core_env()
    
    # Main stuff
    group_name = inquirer.text("Enter a greengrass group name")
    group_version_data = create_greengrass_group(group_name)
    return

def confirm_answer(answer):
    return inquirer.list_input("Your input: " + str(answer), choices=["Confirm", "Redo"])

##################################### Initial env setup
def install_AWS_CLI():
    print("[ AWS CLI ]")
    if os.system("aws --version") != 0:
        print("Downloading AWS CLI ... ")
        r = requests.get('https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip', allow_redirects=True)
        open('awscliv2.zip', 'wb').write(r.content)
        print("Installing AWS CLI ... ")
        with zipfile.ZipFile('awscliv2.zip', 'r') as zip_ref:
            zip_ref.extractall('')
        os.system("sudo ./aws/install")
        os.system("aws --version")
    print("AWS CLI has been installed!")

def configure_aws_access():
    # Note: Need a better way to give access (IAM/Cognito)
    print("[ Configure AWS Access ]")
    if (not os.path.exists(AWS_CONFIG_FOLDER)):
        print("Creating dir: " + AWS_CONFIG_FOLDER)
        os.mkdir(AWS_CONFIG_FOLDER)

    if (not os.path.exists(AWS_CONFIG_FOLDER + "credentials")):
        print("Creating credentials file!")
        f = open(AWS_CONFIG_FOLDER + "credentials", "w")
        f.write("[default]\n")
        f.write("aws_access_key_id=\n")
        f.write("aws_secret_access_key=\n")
        f.close()

    if (not os.path.exists(AWS_CONFIG_FOLDER + "config")):
        print("Creating config file!")
        f = open(AWS_CONFIG_FOLDER + "config", "w")
        f.write("[default]\nregion=us-west-2\noutput=json\n")
        f.close()

    print("AWS access has been configured")

def configure_aws_access_user_input():
    while True:
        questions = [
            inquirer.Text('aws_access_key_id', message="Enter your AWS access key ID"),
            inquirer.Text('aws_secret_access_key', message="Enter your AWS secret access key")
        ]
        answers = inquirer.prompt(questions, theme=inquirer_theme)

        print(answers)

        f = open(AWS_CONFIG_FOLDER + "credentials", "w")
        f.write("[default]\n")
        f.write("aws_access_key_id=" + answers["aws_access_key_id"] + "\n")
        f.write("aws_secret_access_key=" + answers["aws_secret_access_key"] + "\n")
        f.close()

        ret = os.system("aws iot describe-endpoint > /tmp/iot-endpoint-check")
        if ret == 0:
            print("\nYou have provided the correct credentials!\n")
            break
        print("\nThere is something wrong with the credentials you have provided!\nPlease try again!\n")

def setup_greengrass_core_env():
    ret = os.system("wget -O ./greengrass-linux-armv7l-1.11.1.tar.gz https://d1onfpft10uf5o.cloudfront.net/greengrass-core/downloads/1.11.1/greengrass-linux-armv7l-1.11.1.tar.gz")
    print("Success" if ret == 0 else "Failed", ": get gg_env zip file")
    
    ret = os.system("sudo tar -xzvf greengrass-linux-armv7l-1.11.1.tar.gz -C /")
    print("Success" if ret == 0 else "Failed", ": extract gg env folder")
    
    ret = os.system("sudo adduser --system ggc_user")
    print("Success" if ret == 0 else "Failed", ": adduser --system ggc_user")
    
    ret = os.system("sudo addgroup --system ggc_group")
    print("Success" if ret == 0 else "Failed", ": sudo addgroup --system ggc_group")
    

if __name__ == '__main__':
    main()

