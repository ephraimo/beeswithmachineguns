#!/bin/env python

"""
The MIT License

Copyright (c) 2010 The Chicago Tribune & Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from multiprocessing import Pool
from subprocess import check_output, call, CalledProcessError
from collections import OrderedDict
from tempfile import NamedTemporaryFile
#from uuid import uuid4
import os
import re
import socket
import time
import urllib2
import csv
import math
import random

import boto
import boto.ec2
import paramiko

STATE_FILENAME = os.path.expanduser('~/.bees')

# Utilities

def _read_server_list():
    instance_ids = []

    if not os.path.isfile(STATE_FILENAME):
        return (None, None, None, None)

    with open(STATE_FILENAME, 'r') as f:
        username = f.readline().strip()
        key_name = f.readline().strip()
        zone = f.readline().strip()
        text = f.read()
        instance_ids = text.split('\n')

        print 'Read %i bees from the roster.' % len(instance_ids)

    return (username, key_name, zone, instance_ids)

def _write_server_list(username, key_name, zone, instances):
    with open(STATE_FILENAME, 'w') as f:
        f.write('%s\n' % username)
        f.write('%s\n' % key_name)
        f.write('%s\n' % zone)
        f.write('\n'.join([instance.id for instance in instances]))

def _delete_server_list():
    os.remove(STATE_FILENAME)

def _get_pem_path(key):
    return os.path.expanduser('~/.ssh/%s.pem' % key)

def _get_region(zone):
    return zone[:-1] # chop off the "d" in the "us-east-1d" to get the "Region"
	
def _get_security_group_ids(connection, security_group_names, subnet):
    ids = []
    # Since we cannot get security groups in a vpc by name, we get all security groups and parse them by name later
    security_groups = connection.get_all_security_groups()

    # Parse the name of each security group and add the id of any match to the group list
    for group in security_groups:
        for name in security_group_names:
            if group.name == name:
                if subnet == None:
                    if group.vpc_id == None:
                        ids.append(group.id)
                elif group.vpc_id != None:
                    ids.append(group.id)
    if not ids:
        print "Couldn't find security group, probably because you have a default vpc, looking for vpc security groups"
        for group in security_groups:
            for name in security_group_names:
                if group.name == name:
                    ids.append(group.id)
    if not ids:
        print "Warning: Couldn't find security group, using default!!!"
    return ids

# Methods

def up(count, group, zone, image_id, instance_type, username, key_name, subnet):
    """
    Startup the load testing server.
    """
    existing_username, existing_key_name, existing_zone, instance_ids = _read_server_list()

    if instance_ids:
        print 'Bees are already assembled and awaiting orders.'
        return

    count = int(count)

    pem_path = _get_pem_path(key_name)

    if not os.path.isfile(pem_path):
        print 'No key file found at %s' % pem_path
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    print 'Attempting to call up %i bees.' % count

    reservation = ec2_connection.run_instances(
        image_id=image_id,
        min_count=count,
        max_count=count,
        key_name=key_name,
        security_group_ids=_get_security_group_ids(ec2_connection, [group], subnet),
        instance_type=instance_type,
        placement=zone,
        subnet_id=subnet)

    print 'Waiting for bees to load their machine guns...'

    instance_ids = []

    for instance in reservation.instances:
        instance.update()
        while instance.state != 'running':
            print '.'
            time.sleep(5)
            instance.update()

        instance_ids.append(instance.id)

        print 'Bee %s is ready for the attack.' % instance.id

    ec2_connection.create_tags(instance_ids, { "Name": "a bee!" })

    _write_server_list(username, key_name, zone, reservation.instances)

    print 'The swarm has assembled %i bees.' % len(reservation.instances)

def report():
    """
    Report the status of the load testing servers.
    """
    username, key_name, zone, instance_ids = _read_server_list()

    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    for instance in instances:
        print 'Bee %s: %s @ %s' % (instance.id, instance.state, instance.ip_address)

def down():
    """
    Shutdown the load testing server.
    """
    username, key_name, zone, instance_ids = _read_server_list()

    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    print 'Calling off the swarm.'

    terminated_instance_ids = ec2_connection.terminate_instances(
        instance_ids=instance_ids)

    print 'Stood down %i bees.' % len(terminated_instance_ids)

    _delete_server_list()

def _attack(params):
    """
    Test the target URL with requests.

    Intended for use with multiprocessing.
    """
    print 'Bee %i is joining the swarm.' % params['i']

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if params['gnuplot_filename']:
            use_compression = True
        else:
            use_compression = False

        client.connect(
            params['instance_name'],
            username=params['username'],
            key_filename=_get_pem_path(params['key_name']),
            compress=use_compression)

        print 'Bee %i is firing her machine gun (post file: %s) at (%s). Bang bang!' % (params['i'], params['post_file'], params['url'])

        options = ''
        if params['headers'] is not '':
            for h in params['headers'].split(';'):
                options += ' -H "%s"' % h

        stdin, stdout, stderr = client.exec_command('mktemp --suffix=.csv')
        params['csv_filename'] = stdout.read().strip()
        if params['csv_filename']:
            options += ' -e %(csv_filename)s' % params
        else:
            print 'Bee %i lost sight of the target (connection timed out creating csv_filename).' % params['i']
            return None
            
        if params['gnuplot_filename']:
            stdin, stdout, stderr = client.exec_command('mktemp --suffix=.tsv')
            params['tsv_filename'] = stdout.read().strip()
            if params['tsv_filename']:
                options += ' -g %(tsv_filename)s' % params
            else:
                print 'Bee %i lost sight of the target (connection timed out creating tsv_filename).' % params['i']
                return None
            
        if params['post_file']:
            pem_file_path=_get_pem_path(params['key_name'])
            os.system("scp -q -o 'StrictHostKeyChecking=no' -i %s %s %s@%s:/tmp/honeycomb" % (pem_file_path, params['post_file'], params['username'], params['instance_name']))
            options += ' -T "%(mime_type)s; charset=UTF-8" -p /tmp/honeycomb' % params
            #random_command = "sed -i 's/RANDOM/%s/' /tmp/honeycomb && cat /tmp/honeycomb" % str(uuid4())
            #stdin, stdout, stderr = client.exec_command(random_command)
            #print 'posting file: %s' % stdout.read()
            #options += ' -k -T "%(mime_type)s; charset=UTF-8" -p /tmp/honeycomb' % params

        params['options'] = options
        if params['timelimit'] > 0:
            benchmark_command = 'ab -l -r -s 3 -t %(timelimit)s -n 5000000 -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
            #benchmark_command = './ab -l 1000 -r -t %(timelimit)s -n 5000000 -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
            #benchmark_command = 'ab -r -t %(timelimit)s -n 5000000 -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
        else:
            benchmark_command = './ab -l -r -s 3 -n %(num_requests)s -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
            #benchmark_command = './ab -l 1000 -r -n %(num_requests)s -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
            #benchmark_command = 'ab -r -n %(num_requests)s -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(options)s "%(url)s"' % params
        stdin, stdout, stderr = client.exec_command(benchmark_command)

        response = {}

        ab_results = stdout.read()
        ab_error = stderr.read()
        ms_per_request_search = re.search('Time\ per\ request:\s+([0-9.]+)\ \[ms\]\ \(mean\)', ab_results)

        if not ms_per_request_search:
            #print 'Bee %i lost sight of the target (connection timed out running ab).' % params['i']
            print 'Bee %i lost sight of the target (connection timed out running ab). ab command: [%s] \nresult: [%s]\nerror:[%s].' % (params['i'], benchmark_command, ab_results, ab_error)
            return None

        requests_per_second_search = re.search('Requests\ per\ second:\s+([0-9.]+)\ \[#\/sec\]\ \(mean\)', ab_results)
        failed_requests = re.search('Failed\ requests:\s+([0-9.]+)', ab_results)
        complete_requests_search = re.search('Complete\ requests:\s+([0-9]+)', ab_results)
        time_taken_search = re.search('Time\ taken\ for\ tests:\s+([0-9]+)', ab_results)
        non_200_responses_search = re.search('Non\-2xx\ responses:\s+([0-9]+)', ab_results)
        
        """
        If there are failed requests, get the breakdown
        (Connect: 0, Receive: 0, Length: 338, Exceptions: 0)
        """
        failed_connect_search = re.search('\s+\(Connect:\s+([0-9.]+)', ab_results)
        failed_receive_search = re.search('\s+\(.+Receive:\s+([0-9.]+)', ab_results)
        failed_length_search = re.search('\s+\(.+Length:\s+([0-9.]+)', ab_results)
        failed_exceptions_search = re.search('\s+\(.+Exceptions:\s+([0-9.]+)', ab_results)

        response['ms_per_request'] = float(ms_per_request_search.group(1))
        response['requests_per_second'] = float(requests_per_second_search.group(1))
        response['failed_requests'] = float(failed_requests.group(1))
        response['complete_requests'] = float(complete_requests_search.group(1))
        response['time_taken'] = float(time_taken_search.group(1))
        
        if failed_connect_search is None:
            response['failed_connect'] = 0
        else:
            response['failed_connect'] = float(failed_connect_search.group(1))
        
        if failed_receive_search is None:
            response['failed_receive'] = 0
        else:
            response['failed_receive'] = float(failed_receive_search.group(1))
            
        if failed_length_search is None:
            response['failed_length'] = 0
        else:
            response['failed_length'] = float(failed_length_search.group(1))
            
        if failed_exceptions_search is None:
            response['failed_exceptions'] = 0
        else:
            response['failed_exceptions'] = float(failed_exceptions_search.group(1))
        
        if non_200_responses_search is None:
            response['non_200_responses'] = 0
        else:
            response['non_200_responses'] = float(non_200_responses_search.group(1))

        print 'Bee %i is out of ammo. She is collecting her pollen and flying back to the hive. This may take a while if she has a heavy load and/or the hive is far away...' % params['i']

        stdin, stdout, stderr = client.exec_command('cat %(csv_filename)s' % params)
        response['request_time_cdf'] = []
        for row in csv.DictReader(stdout):
            row["Time in ms"] = float(row["Time in ms"])
            response['request_time_cdf'].append(row)
        if not response['request_time_cdf']:
            print 'Bee %i lost sight of the target (connection timed out reading csv).' % params['i']
            return None

        if params['gnuplot_filename']:
            f = NamedTemporaryFile(suffix=".tsv", delete=False)
            response['tsv_filename'] = f.name
            f.close()
            sftp = client.open_sftp()
            sftp.get(params['tsv_filename'], response['tsv_filename'])

        client.close()

        return response
    except socket.error, e:
        return e

def _print_results(results, params, csv_filename, gnuplot_filename, stats_filename, existing_stats_file, testname, non_200_is_failure):
    """
    Print summarized load-testing results.
    """
    timeout_bees = [r for r in results if r is None]
    exception_bees = [r for r in results if type(r) == socket.error]
    complete_bees = [r for r in results if r is not None and type(r) != socket.error]

    timeout_bees_params = [p for r,p in zip(results, params) if r is None]
    exception_bees_params = [p for r,p in zip(results, params) if type(r) == socket.error]
    complete_bees_params = [p for r,p in zip(results, params) if r is not None and type(r) != socket.error]

    num_timeout_bees = len(timeout_bees)
    num_exception_bees = len(exception_bees)
    num_complete_bees = len(complete_bees)

    if exception_bees:
        print '     %i of your bees didn\'t make it to the action. They might be taking a little longer than normal to find their machine guns, or may have been terminated without using "bees down".' % num_exception_bees

    if timeout_bees:
        print '     Target timed out without fully responding to %i bees.' % num_timeout_bees

    if num_complete_bees == 0:
        print '     No bees completed the mission. Apparently your bees are peace-loving hippies.'
        return

    complete_requests = [r['complete_requests'] for r in complete_bees]
    total_complete_requests = sum(complete_requests)
    print '     Complete requests:\t\t%i' % total_complete_requests

    if non_200_is_failure:
        failed_requests = [r['failed_requests']+r['non_200_responses'] for r in complete_bees]
    else:
        failed_requests = [r['failed_requests'] for r in complete_bees]

    total_failed_requests = sum(failed_requests)
    total_failed_percent = total_failed_requests/total_complete_requests
    print '     Failed requests:\t\t{:,} ({:.2%})'.format(int(total_failed_requests), total_failed_percent)

    non_200_results = [r['non_200_responses'] for r in complete_bees]
    total_non_200_results = sum(non_200_results)

    if total_failed_requests > 0:
        failed_connect_requests = [r['failed_connect'] for r in complete_bees]
        total_failed_connect_requests = sum(failed_connect_requests)
        failed_receive_requests = [r['failed_receive'] for r in complete_bees]
        total_failed_receive_requests = sum(failed_receive_requests)
        failed_length_requests = [r['failed_length'] for r in complete_bees]
        total_failed_length_requests = sum(failed_length_requests)
        failed_exceptions_requests = [r['failed_exceptions'] for r in complete_bees]
        total_failed_exception_requests = sum(failed_exceptions_requests)
        if non_200_is_failure:
            print '         (Connect: %i, Receive: %i, Length: %i, Exception: %i, Non-200: %i)' % \
                (total_failed_connect_requests, total_failed_receive_requests, total_failed_length_requests, total_failed_exception_requests, total_non_200_results)
        else:
            print '         (Connect: %i, Receive: %i, Length: %i, Exception: %i)' % \
                (total_failed_connect_requests, total_failed_receive_requests, total_failed_length_requests, total_failed_exception_requests)

    if (not non_200_is_failure) and total_non_200_results > 0:
        print '     Non-200 Responses:\t\t%i' % total_non_200_results

    requests_per_second = [r['requests_per_second'] for r in complete_bees]
    mean_requests = sum(requests_per_second)
    print '     Requests per second:\t%f [#/sec]' % mean_requests

    if non_200_is_failure:
        successful_requests_per_second = [(r['complete_requests']-r['failed_requests']-r['non_200_responses'])/r['time_taken'] for r in complete_bees]
    else:
        successful_requests_per_second = [(r['complete_requests']-r['failed_requests'])/r['time_taken'] for r in complete_bees]
    successful_mean_requests = sum(successful_requests_per_second)
    print '     Successful Requests per second:\t%f [#/sec]' % successful_mean_requests

    ms_per_request = [r['ms_per_request'] for r in complete_bees]
    mean_response = sum(ms_per_request) / num_complete_bees
    print '     Time per request:\t\t%f [ms] (mean of bees)' % mean_response

    # Recalculate the global cdf based on the csv files collected from
    # ab. Can do this by sampling the request_time_cdfs for each of
    # the completed bees in proportion to the number of
    # complete_requests they have
    n_final_sample = 100
    sample_size = 100*n_final_sample
    n_per_bee = [int(r['complete_requests']/total_complete_requests*sample_size)
                 for r in complete_bees]
    sample_response_times = []
    for n, r in zip(n_per_bee, complete_bees):
        cdf = r['request_time_cdf']
        for i in range(n):
            j = int(random.random()*len(cdf))
            sample_response_times.append(cdf[j]["Time in ms"])
    sample_response_times.sort()
    request_time_cdf = sample_response_times[0:sample_size:sample_size/n_final_sample]

    print '     50%% responses faster than:\t%f [ms]' % request_time_cdf[49]
    print '     90%% responses faster than:\t%f [ms]' % request_time_cdf[89]

    if mean_response < 500 and total_failed_percent < 0.001:
        print 'Mission Assessment: Target crushed bee offensive.'
    elif mean_response < 1000 and total_failed_percent < 0.01:
        print 'Mission Assessment: Target successfully fended off the swarm.'
    elif mean_response < 1500 and total_failed_percent < 0.05:
        print 'Mission Assessment: Target wounded, but operational.'
    elif mean_response < 2000 and total_failed_percent < 0.10:
        print 'Mission Assessment: Target severely compromised.'
    else:
        print 'Mission Assessment: Swarm annihilated target.'

    if csv_filename:
        with open(csv_filename, 'w') as stream:
            writer = csv.writer(stream)
            header = ["% faster than", "all bees [ms]"]
            for p in complete_bees_params:
                header.append("bee %(instance_id)s [ms]" % p)
            writer.writerow(header)
            for i in range(100):
                row = [i, request_time_cdf[i]]
                for r in results:
                    row.append(r['request_time_cdf'][i]["Time in ms"])
                writer.writerow(row)

    if gnuplot_filename:
        print 'Joining gnuplot files from all bees.'
        files = [r['tsv_filename'] for r in results if r is not None]
        # using csvkit utils to join the tsv files from all of the bees, adding a column to show which bee produced each line. using sort because of performance problems with csvsort.
        #command = "csvstack -t -n bee -g " + ",".join(["%(i)s" % p for p in complete_bees_params]) + " " + " ".join(files) + " | csvcut -c 2-7,1 | sort -nk 5 -t ',' | sed 's/,/\t/g' > " + gnuplot_filename
        # csvkit took too long for joining files, using builtins instead
        command = "head -1 " + files[0] + " > " + gnuplot_filename + " && cat " + " ".join(files) + " | grep -v starttime >> " + gnuplot_filename
        call(command, shell=True)
        # removing temp files
        call(["rm"] + files)

    if stats_filename:
        print 'Calculating statistics.'
        try:
            csvstat_results = check_output(["csvstat", "-tc", "ttime", gnuplot_filename])
        except CalledProcessError as e:
            print 'Error running csvstat: %d output: [%s]' % (e.returncode, e.output)
            csvstat_results = """
                               Dummy values:
                               Min: 0
                               Max: 0
                               Mean: 0
                               Median: 0
                               Standard Deviation: 0
                              """

        min_search = re.search('\sMin:\s+([0-9]+)', csvstat_results)
        max_search = re.search('\sMax:\s+([0-9]+)', csvstat_results)
        mean_search = re.search('\sMean:\s+([0-9.]+)', csvstat_results)
        median_search = re.search('\sMedian:\s+([0-9.]+)', csvstat_results)
        stdev_search = re.search('\sStandard\ Deviation:\s+([0-9.]+)', csvstat_results)

        stats = OrderedDict()
        stats['Name'] = testname
        stats['Total'] = int(total_complete_requests)
        stats['Success'] = int(total_complete_requests-total_failed_requests)
        stats['% Success'] = stats['Success']/total_complete_requests
        stats['Error'] = int(total_failed_requests)
        stats['% Error'] = total_failed_percent
        stats['TotalPerSecond'] = mean_requests
        stats['SuccessPerSecond'] = successful_mean_requests
        stats['Min'] = int(min_search.group(1))
        stats['Max'] = int(max_search.group(1))
        stats['Mean'] = float(mean_search.group(1))
        stats['Median'] = float(median_search.group(1))
        stats['StdDev'] = float(stdev_search.group(1))
        for i in range(5, 100, 5):
            stats['P' + str(i)] = request_time_cdf[i]

        with open(stats_filename, 'a') as stream:
            writer = csv.DictWriter(stream, fieldnames=stats)
            if not existing_stats_file:
                writer.writeheader()
            writer.writerow(stats)
    
def attack(urls, n, c, t, **options):
    """
    Test the root url of this site.
    """
    username, key_name, zone, instance_ids = _read_server_list()
    headers = options.get('headers', '')
    csv_filename = options.get("csv_filename", '')
    gnuplot_filename = options.get("gnuplot_filename", '')
    stats_filename = options.get("stats_filename", '')
    existing_stats_file = False
    testname = options.get("testname", '')
    non_200_is_failure = options.get("non_200_is_failure", False)

    if csv_filename:
        try:
            stream = open(csv_filename, 'w')
        except IOError, e:
            raise IOError("Specified csv_filename='%s' is not writable. Check permissions or specify a different filename and try again." % csv_filename)
    
    if stats_filename:
        existing_stats_file = os.path.isfile(stats_filename)
        try:
            stream = open(stats_filename, 'a')
        except IOError, e:
            raise IOError("Specified stats_filename='%s' is not writable. Check permissions or specify a different filename and try again." % stats_filename)
        if not gnuplot_filename:
            gnuplot_filename = os.path.splitext(stats_filename)[0] + "." + testname + ".tsv"

    if gnuplot_filename:
        try:
            stream = open(gnuplot_filename, 'w')
        except IOError, e:
            raise IOError("Specified gnuplot_filename='%s' is not writable. Check permissions or specify a different filename and try again." % gnuplot_filename)

    if not instance_ids:
        print 'No bees are ready to attack.'
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    print 'Assembling bees.'

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    instance_count = len(instances)

    if c < instance_count:
        instance_count = c
        del instances[c:]
        print 'bees: warning: the number of concurrent requests is lower than the number of bees, only %d of the bees will be used' % instance_count
    connections_per_instance = int(float(c) / instance_count)
    if instance_count < len(urls):
        print "bees: error: the number of urls (%d) can't exceed the number of bees (%d)" % (len(urls), instance_count)
        return
    if instance_count % len(urls):
       print "bees: warning: the load will not be evenly distributed between the urls because they can't be evenly divided between the bees [(%d bees) mod (%d urls) != 0]" % (instance_count, len(urls))
    post_files = options.get('post_files')
    if post_files:
        if instance_count < len(post_files):
            print "bees: error: the number of post_files (%d) can't exceed the number of bees (%d)" % (len(post_files), instance_count)
            return
        if instance_count % len(post_files):
            print "bees: warning: the load will not be evenly distributed between the post_files because they can't be evenly divided between the bees [(%d bees) mod (%d post_files) != 0]" % (instance_count, len(post_files))
    if t > 0:
        print 'Each of %i bees will fire for %s seconds, %s at a time.' % (instance_count, t, connections_per_instance)
        requests_per_instance = 50000;
    else:
        if n < instance_count * 2:
            print 'bees: error: the total number of requests must be at least %d (2x num. instances)' % (instance_count * 2)
            return
        if n < c:
            print 'bees: error: the number of concurrent requests (%d) must be at most the same as number of requests (%d)' % (c, n)
            return

        requests_per_instance = int(float(n) / instance_count)

        print 'Each of %i bees will fire %s rounds, %s at a time.' % (instance_count, requests_per_instance, connections_per_instance)

    params = []

    for i, instance in enumerate(instances):
        post_file = False
        if post_files:
            post_file = post_files[len(post_files) - (i % len(post_files)) - 1] # reverse iteration so it won't coinside with the urls iteration
        params.append({
            'i': i,
            'instance_id': instance.id,
            'instance_name': instance.public_dns_name,
            'url': urls[i % len(urls)],
            #'url': urls[i % len(urls)] + "?uuid=" + str(uuid4()),
            'concurrent_requests': connections_per_instance,
            'num_requests': requests_per_instance,
            'timelimit': t,
            'username': username,
            'key_name': key_name,
            'headers': headers,
            'post_file': post_file,
            'mime_type': options.get('mime_type', ''),
            'gnuplot_filename': gnuplot_filename,
        })

#    print 'Stinging URLs so they will be cached for the attack.'

    # Ping url so it will be cached for testing
#    dict_headers = {}
#    if headers is not '':
#        dict_headers = headers = dict(h.split(':') for h in headers.split(';'))
#    for url in urls:
#        request = urllib2.Request(url, headers=dict_headers)
#        urllib2.urlopen(request).read()

    print 'Organizing the swarm.'

    # Spin up processes for connecting to EC2 instances
    pool = Pool(len(params))
    results = pool.map(_attack, params)

    print 'Offensive complete.'

    _print_results(results, params, csv_filename, gnuplot_filename, stats_filename, existing_stats_file, testname, non_200_is_failure)

    print 'The swarm is awaiting new orders.'
