# Useful notes:
#
# Roll the cluster without upgrading:
# fab -f rolling_upgrade -R elasticsearch roll_elastic_cluster:upgrade='no',searchguard='no'
#
# Rolling upgrade with SG upgrade:
# fab -f rolling_upgrade -R elasticsearch roll_elastic_cluster:upgrade='yes',searchguard='yes'
#
# Rolling upgrade without SG upgrade:
# fab -f rolling_upgrade -R elasticsearch roll_elastic_cluster:upgrade='yes',searchguard='no'
#

from fabric.api import *
from fabric.tasks import execute
from fabric.colors import *
import time
from datetime import datetime
import subprocess
import json

env.roledefs['elasticsearch'] = [
    'el0.grnet.gr',
    'el1.grnet.gr',
    'el2.grnet.gr',
    'el3.grnet.gr',
    'el4.grnet.gr',
    'el5.grnet.gr',
    'el6.grnet.gr',
    'el7.grnet.gr',
    'logstash.grnet.gr',
    'logstash2.grnet.gr',
    'logstash3.grnet.gr',
    'logstash-web.grnet.gr'
    ]

env.roledefs['logstash'] = [
    'logstash.grnet.gr',
    'logstash2.grnet.gr',
    'logstash3.grnet.gr'
    ]

env.roledefs['staging'] = [
    'el0.staging.grnet.gr',
    'el1.staging.grnet.gr',
    'el2.staging.grnet.gr'
    ]

# elasticsearch-SG compatibility table, has to be adapted to ES 2.x and SG 2.x
searchguard_version = {"1.5.2" : "0.5", "1.7.5" : "1.7.3.0"}

@task
#@roles('elasticsearch')
def roll_elastic_cluster(upgrade, searchguard):
    roll_elastic_node(upgrade, searchguard)

@task
@serial
#@roles('staging')
def roll_elastic_node(upgrade, searchguard):
    print(green(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
        green("Connected to: ") + green(env.host))

    # verifying cluster health, only continue if green
    health_status = verify_cluster_health()
    if health_status == "green":
        print(green(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            green("Cluster health status: green. Proceeding."))
    else:
        exit(red(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) + red("Cluster health status: ") + red(health_status) + red(". Process cannot continue. Exiting."))

    # schedule downtime in the node
    sudo("python /usr/local/bin/ici -dt 3600")

    # disable puppet
    sudo("puppet agent --disable 'ES rolling upgrade'")

    # checking if there is logstash running in the host and stopping it
    # also unmonitor logstash
    if env.host in env.roledefs['logstash']:
        sudo("monit unmonitor logstash")
        service_stop('logstash')

    stop_elastic_node()

    if upgrade == 'yes':
        if elast_ver_avail() != 0:
            new_elasticsearch_version = elast_ver_avail()
            print(cyan(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
                cyan("New version found. Proceeding."))
            if searchguard == 'yes':
                if upgrade_searchguard_plugin(new_elasticsearch_version) != 0:
                    abort("Searchguard plugin upgrade failed. Will not proceed to elasticsearch upgrade. Aborting and exiting the process. Please check your system.")
            install_package()
        else:
            print(green(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
                green("Current version is up-to-date. Not upgrading."))

    start_elastic_node()

    # starting logstash again in the relevant hosts and monitoring it
    if env.host in env.roledefs['logstash']:
        service_start('logstash')
        sudo("monit monitor logstash")

    # enable again puppet
    sudo("puppet agent --enable")

    time.sleep(5)

@task
def stop_elastic_node():
    # disable shard allocation
    shard_allocation('none')
    # stop the service
    service_stop('elasticsearch')

    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Shard allocation disabled. Elasticsearch stopped."))

    time.sleep(5)

@task
def start_elastic_node():
    # start the service
    service_start('elasticsearch')

    # verify joined cluster before sending any cluster level commands like
    # shard allocation modifications etc
    verify_node_joined_cluster()

    # enabling allocation and wating for cluster health status to be green again
    shard_allocation('all')

    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Elasticsearch started, shard allocation enabled. Waiting for cluster to become healthy..."))

    # verifying cluster health after restart, only continue if elasticsearch is running and we can connect to the cluster
    health_status = verify_cluster_health()
    while (health_status != "green"):
        time.sleep(5)
        health_status = verify_cluster_health()

@task
def upgrade_searchguard_plugin(new_elasticsearch_version):
    # find new SG version (only covers ES 1.x and SG 1.x)
    if new_elasticsearch_version in searchguard_version:
        sg_version = searchguard_version[new_elasticsearch_version]
    # has to be adapted to ES 2.x and SG 2.x
    else:
        print(red("There is no SG version compatible with the new elasticsearch version you are going to install, please proceed with caution!"))

    if sg_version:
        # remove previous version
        out = sudo("/usr/share/elasticsearch/bin/plugin -r search-guard", warn_only=True)
        if (out.return_code != 0):
            print(red("There was a problem while removing SG plugin. Exiting."))
            return 1
        else:
            print(yellow("Installing searchguard version " + sg_version))
            # install new searchguard version
            output = sudo("/usr/share/elasticsearch/bin/plugin -i com.floragunn/search-guard/" + sg_version)
            if (output.return_code != 0):
                print(red("Searchguard version " + sg_version + " failed to install. Searchguard plugin is not installed at all. Exiting."))
                return 1
            else:
                print(green("Searchguard version " + sg_version + " installed. Proceeding to elasticsearch version upgrade to " + new_elasticsearch_version))
                return 0
    else:
        # no SG version compatible with the new elastic version
        return 0

def verify_node_joined_cluster():
    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Waiting for ") + yellow(env.host) + yellow(" to join the cluster..."))

    out = sudo("curl -XGET 'http://localhost:9200/_cluster/health?pretty'", warn_only=True)

    while (out.return_code != 0):
        time.sleep(5)
        out = sudo("curl -XGET 'http://localhost:9200/_cluster/health?pretty'", warn_only=True)

    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow(env.host) + yellow(" joined the cluster."))

def verify_cluster_health():
    out = sudo("curl -XGET 'http://localhost:9200/_cluster/health'", warn_only=True)
    while (out.return_code != 0):
        time.sleep(5)
        out = sudo("curl -XGET 'http://localhost:9200/_cluster/health'", warn_only=True)

    cl_health = json.loads(sudo("curl -XGET 'http://localhost:9200/_cluster/health'", warn_only=True))
    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Cluster health status:") + yellow(cl_health["status"]))

    return cl_health["status"]

def shard_allocation(alloc):
    node_info = json.loads(sudo("curl -XGET 'http://localhost:9200/_nodes/" +
        env.host  +  "/info/settings'", warn_only=True))
    node_id_key=node_info["nodes"].keys()
    node_id=node_id_key[0]

    # Modify shard allocation only if the node is data node
    if node_info['nodes'][node_id]['settings']['node']['data'] == 'true':

        sudo("curl -XPUT localhost:9200/_cluster/settings -d '{\
            \"transient\" : {\"cluster.routing.allocation.enable\" : \"" + alloc + "\"}}'")

        print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Shard allocation changed to: ") + yellow(alloc))
    else:
        print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow("Node does not hold data. Shard allocation is not modified."))


def elast_ver_avail():
    ver_available = sudo("apt-cache policy elasticsearch | grep 'Candidate:' | awk '{print $2}'")
    ver_installed = sudo("apt-cache policy elasticsearch | grep 'Installed:' | awk '{print $2}'")
    if ver_installed != ver_available:
        print "Elasticsearch update available. Candidate:" + ver_available + ". Installed:" + ver_installed + "."
        return ver_available
    else:
        print("No updates found. Exiting.")
        return 0

def service_stop(serv_name):
    out = sudo("service " + serv_name + " stop", warn_only=True)
    while out.return_code != 0:
        out = sudo("service " + serv_name + " stop", warn_only=True)
    print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            yellow(serv_name) + yellow(" stopped on ") + yellow(env.host))

def service_start(serv_name):
    out = sudo("service " + serv_name + " start", warn_only=True)
    if out.return_code == 0:
        print(yellow(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
                yellow(serv_name) + yellow(" started on ") + yellow(env.host))
    else:
        print(red(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
                red(serv_name) + red(" failed to start on ") + red(env.host))
        abort("Aborting and exiting the process.")

def install_package():
    _out = sudo("apt-get install elasticsearch", warn_only=True)
    if _out.return_code == 0:
        print(cyan(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            cyan("Packages upgraded on: ") + cyan(env.host))
    else:
        print(red(datetime.now().strftime('[%d/%b/%Y %H:%M:%S] ')) +
            red("Installation failed on: ") + red(env.host))
        abort("Aborting and exiting the process.")
