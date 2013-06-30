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

import bees
from urlparse import urlparse

from argparse import ArgumentParser

def parse_options():
    """
    Handle the command line arguments for spinning up bees
    """
    parser = ArgumentParser(description="""
        Bees with Machine Guns.
        A utility for arming (creating) many bees (small EC2 instances) to attack
        (load test) targets (web applications).
        """)

    subparsers = parser.add_subparsers(title='commands', dest='command')
    up_cmd = subparsers.add_parser("up", help='Start a batch of load testing servers.', description=
        """Start a batch of load testing servers.
        In order to spin up new servers you will need to specify at least the -k command, which is the name of the EC2 keypair to use for creating and connecting to the new servers. The bees will expect to find a .pem file with this name in ~/.ssh/.""")

    # Required
    up_cmd.add_argument('-k', '--key',  metavar="KEY", dest='key', required=True, help="The ssh key pair name to use to connect to the new servers.")

    up_cmd.add_argument('-s', '--servers', metavar="SERVERS", dest='servers', type=int, default=5, help="The number of servers to start (default: 5).")
    up_cmd.add_argument('-g', '--group', metavar="GROUP", dest='group', default='default', help="The security group(s) to run the instances under (default: default).")
    up_cmd.add_argument('-z', '--zone',  metavar="ZONE", dest='zone', default='us-east-1d', help="The availability zone to start the instances in (default: us-east-1d).")
    up_cmd.add_argument('-i', '--instance',  metavar="INSTANCE", dest='instance', default='ami-ff17fb96', help="The instance-id to use for each server from (default: ami-ff17fb96).")
    up_cmd.add_argument('-t', '--type',  metavar="TYPE", dest='type', default='t1.micro', help="The instance-type to use for each server (default: t1.micro).")
    up_cmd.add_argument('-l', '--login',  metavar="LOGIN", dest='login', default='newsapps', help="The ssh username name to use to connect to the new servers (default: newsapps).")
    up_cmd.add_argument('-v', '--subnet',  metavar="SUBNET", dest='subnet', default=None, help="The vpc subnet id in which the instances should be launched. (default: None).")

    attack_cmd = subparsers.add_parser("attack", help='Begin the attack on a specific url.', description=
        """Begin the attack on a specific url.
        Beginning an attack requires only that you specify the -u option with the URL you wish to target.""")

    # Required
    attack_cmd.add_argument('-u', '--url', metavar="URL", dest='url', required=True, help="URL of the target to attack.")

    attack_cmd.add_argument('-p', '--post-file',  metavar="POST_FILE", dest='post_file', default=False, help="The POST file to deliver with the bee's payload.")
    attack_cmd.add_argument('-m', '--mime-type',  metavar="MIME_TYPE", dest='mime_type', default='text/plain', help="The MIME type to send with the request.")
    attack_cmd.add_argument('-n', '--number', metavar="NUMBER", dest='number', type=int, default=1000, help="The number of total connections to make to the target (default: 1000).")
    attack_cmd.add_argument('-c', '--concurrent', metavar="CONCURRENT", dest='concurrent', type=int, default=100, help="The number of concurrent connections to make to the target (default: 100).")
    attack_cmd.add_argument('-H', '--headers', metavar="HEADERS", dest='headers', default='',
                        help="HTTP headers to send to the target to attack. Multiple headers should be separated by semi-colons, e.g header1:value1;header2:value2")
    attack_cmd.add_argument('-e', '--csv', metavar="FILENAME", dest='csv_filename', default='', help="Store the distribution of results in a csv file for all completed bees (default: '').")

    down_cmd = subparsers.add_parser("down", help='Shutdown and deactivate the load testing servers.', description='Shutdown and deactivate the load testing servers.')
    report_cmd = subparsers.add_parser("report", help='Report the status of the load testing servers.', description='Report the status of the load testing servers.')

    options = parser.parse_args()

    command = options.command

    if command == 'up':
        if options.group == 'default':
            print 'New bees will use the "default" EC2 security group. Please note that port 22 (SSH) is not normally open on this group. You will need to use to the EC2 tools to open it before you will be able to attack.'
 
        bees.up(options.servers, options.group, options.zone, options.instance, options.type, options.login, options.key, options.subnet)
    elif command == 'attack':
        parsed = urlparse(options.url)
        if not parsed.scheme:
            parsed = urlparse("http://" + options.url)

        if not parsed.path:
            parser.error('It appears your URL lacks a trailing slash, this will disorient the bees. Please try again with a trailing slash.')

        additional_options = dict(
            headers=options.headers,
            post_file=options.post_file,
            mime_type=options.mime_type,
            csv_filename=options.csv_filename,
        )

        bees.attack(options.url, options.number, options.concurrent, **additional_options)

    elif command == 'down':
        bees.down()
    elif command == 'report':
        bees.report()

def main():
    parse_options()
