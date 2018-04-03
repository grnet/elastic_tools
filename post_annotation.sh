#!/bin/bash

help=$'Script to post annotations to elasticsearch index\n
Usage: ./post_annotation.sh [TITLE] [MESSAGE] [PROJECT] [ENVIRONMENT] [TAGS]\n
TITLE and MESSAGE are optional, if there is no title/message to be posted use \' \' instead.\t
PROJECT, ENVIRONMENT and TAGS are mandatory.\n
Examples:\t
    ./post_annotation.sh \'service version 1.x\' SYSADMIN-xxxx service production deploy\t
    ./post_annotation.sh \'service outage\' \' \' service test outage\n

It is assumed that the elasticsearch cluster is secured and user authentication is requested for posting.

Author: katerina@noc.grnet.gr
'

date=$(date -u +"%Y-%m-%dT%H:%M:%SZ")


# check the number of arguments, do not proceed if they are not exactly 5
if [ $# -ne 5 ];
  then
      echo "$help"
      exit 0
fi

title="$1"
msg="$2"

# do not proceed if any project/environment/tags is empty
if [ -z "${3// }" ] ||[ -z "${4// }" ] || [ -z "${5// }" ];
  then
      echo "$help"
      exit 0
  else
      project=$3
      env=$4
      tags=$5
fi

echo '{
    "@timestamp" : "'${date}'",
    "title" : "'${title}'",
    "message" : "'${msg}'",
    "project" : "'${project}'",
    "environment" : "'${env}'",
    "tags" : "'${tags}'"
}' > /tmp/annotationdata

if [ -f /tmp/annotationdata ];
  then
      curl -XPOST 'http://<USERNAME>:<PASSWORD>@<ELASTICSEARCH_URL>:<ELASTICSEARCH_PORT>/annotations/event' -d @/tmp/annotationdata
  else
      echo "POST to elasticsearch annotation index failed. Please repeat the operation."
fi

rm -f /tmp/annotationdata

