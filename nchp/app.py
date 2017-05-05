import os
import stat
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit, urlunsplit

import jinja2
from traitlets import Unicode, Integer, Dict
from traitlets.config import Application

from nchp.dnsutils import get_nameservers

def parse_proxy_streams_string(s):
    streams = {}
    try:
        for mapping in s.split(';'): # ['90=10.0.0.2:800','8889=10.2.3.4:8001']
            proxy_port , target = mapping.split('=')
            streams[proxy_port] = target
    except Exception as e:
        print('Badly formatted proxy streams string "{}" : Error: {}'.format(s,e))
    return streams # {'90':'10.0.0.2.800','8889':'10.2.3.4:8001'}

class NCHPApp(Application):
    name = Unicode("nchp")

    aliases = Dict({
        'ip': 'NCHPApp.public_ip',
        'port': 'NCHPApp.public_port',
        'api-ip': 'NCHPApp.api_ip',
        'api-port': 'NCHPApp.api_port',
        'default-target': 'NCHPApp.default_target',
        'ssl-key': 'NCHPApp.public_ssl_key',
        'ssl-cert': 'NCHPApp.public_ssl_cert',
        'ssl-ciphers': 'NCHPApp.public_ssl_ciphers',
        'ssl-dhparam': 'NCHPApp.public_ssl_dhparam',
        'api-ssl-key': 'NCHPApp.api_ssl_key',
        'api-ssl-cert': 'NCHPApp.api_ssl_cert',
        'api-ssl-ciphers': 'NCHPApp.api_ssl_ciphers',
        'api-ssl-dhparam': 'NCHPApp.api_ssl_dhparam',
        # FIXME: Actually implement this! Adding this to make nchp work with
        # newer versions of jupyterhub
        'error-target': 'NCHPApp.error_target',
        'error-path': 'NCHPApp.error_path',
        'config': 'NCHPApp.config_file',
        'client-max-body-size': 'NCHPApp.client_max_body_size',
    })

    config_file = Unicode('',
        config=True,
        help='Path to config file to read config parameters from'
    )
    dns_resolver = Unicode(
        config=True,
        help='DNS resolver for nginx to use'
    )
    def _dns_resolver_default(self):
        return get_nameservers()[0]

    public_ip = Unicode(
        '0.0.0.0',
        config=True,
        help='Public facing IP of the proxy'
    )

    public_port = Integer(
        8000,
        config=True,
        help='Public facing port of the proxy'
    )

    default_target = Unicode(
        config=True,
        help='Default proxy target (proto://host[:port])'
    )

    api_port = Integer(
        8001,
        config=True,
        help='Inward facing port for API requests'
    )

    api_ip = Unicode(
        '127.0.0.1',
        config=True,
        help='Inward facing IP for API requests'
    )

    proxy_streams = Unicode(
        os.environ.get('PROXY_STREAMS', ''),
        config=True,
        help='string of the form "<proxy-port>=<ip>:<port>;..." of additional ports to forward'
    )

    auth_token = Unicode(
        os.environ.get('CONFIGPROXY_AUTH_TOKEN', ''),
        config=True,
        help='Auth token to use when talking to the proxy'
    )

    nginx_path = Unicode(
        '/usr/sbin/nginx',
        config=True,
        help='Full path to nginx executable to use'
    )

    public_ssl_cert = Unicode(
        config=True,
        help='Path to the SSL certificate for public facing proxy'
    )

    public_ssl_key = Unicode(
        config=True,
        help='Path to the SSL key for public facing proxy'
    )

    # Default to strong SSL Ciphers as of 2016-02-13, stolen from Wikimedia
    public_ssl_ciphers = Unicode(
        ':'.join([
            'ECDHE-ECDSA-AES128-GCM-SHA256',
            'ECDHE-RSA-AES128-GCM-SHA256',
            'ECDHE-ECDSA-AES256-GCM-SHA384',
            'ECDHE-RSA-AES256-GCM-SHA384',
            'DHE-RSA-AES128-GCM-SHA256',
            'DHE-RSA-AES256-GCM-SHA384'
        ]),
        config=True,
        help=': separated list of ciphers used to serve public SSL'
    )

    public_ssl_dhparam = Unicode(
        config=True,
        help='SSL Diffie-Helman Parameters file (if any)'
    )

    api_ssl_cert = Unicode(
        config=True,
        help='Path to the SSL certificate for private api'
    )

    api_ssl_key = Unicode(
        config=True,
        help='Path to the SSL key for private API'
    )

    # Default to strong SSL Ciphers as of 2016-02-13, stolen from Wikimedia
    api_ssl_ciphers = Unicode(
        ':'.join([
            'ECDHE-ECDSA-AES128-GCM-SHA256',
            'ECDHE-RSA-AES128-GCM-SHA256',
            'ECDHE-ECDSA-AES256-GCM-SHA384',
            'ECDHE-RSA-AES256-GCM-SHA384',
            'DHE-RSA-AES128-GCM-SHA256',
            'DHE-RSA-AES256-GCM-SHA384'
        ]),
        config=True,
        help=': separated list of ciphers used to serve api SSL'
    )

    api_ssl_dhparam = Unicode(
        config=True,
        help='SSL Diffie-Helman Parameters file (if any)'
    )

    error_path = Unicode(
        config=True,
        help='Path to folder containing nicer looking files to serve on errors. NOT IMPLEMENTED YET'
    )

    error_target = Unicode(
        config=True,
        help='Target to route to on error. NOT IMPLEMENTED YET'
    )

    extra_public_nginx_config = Unicode(
        config=True,
        help='Raw nginx config that will be added to the public facing nginx server\'s server directive',
    )

    def access_log_dest(self):
        """
        Return the destination for access logs

        If we're running this as a systemd service, systemd
        makes /dev/stdout and friends be sockets that lead
        into journald, rather than files. This confuses
        nginx, which expects to `open()` them like normal
        files. nginx supports 'stderr' as a directive for
        error_log, but *not* access log. Since we still
        want to get them out into stderr, we hack this in.

        If /dev/stdout is a socket, we then write to syslog.
        JournalD also picks up syslog, so the end result is
        the same from an admin's pov. Just uglier and hackier

        I guess the 'right' thing here is for nginx to
        support `stderr` as a target in access_log just like
        for `error_log`
        """
        path = '/dev/stdout'
        if stat.S_ISSOCK(os.stat(path).st_mode):
            return 'syslog:server=unix:/dev/log,nohostname'
        return path

    # performance tuning!
    client_max_body_size = Unicode(
        '256M',
        help='Maximum size of client uploads. This limits notebook sizes. Accepts common byte suffixes (M/k/G). Set 0 to disable limit',
        config=True
    )

    def initialize(self, argv=None):
        self.parse_command_line(argv)

    def build_nginx_conf(self):
        # FIXME: Use PackageLoader here!
        env = jinja2.Environment(
            loader=jinja2.PackageLoader(
                'nchp',
                'templates'
            )
        )
        template = env.get_template('nginx.conf')

        # HACK: Replace localhost with 127.0.0.1
        # Reasons:
        #   - Some DNS servers do not resolve localhost
        #     to 127.0.0.1 (such as 8.8.8.8). So anyone
        #     using such DNS servers will have this fail,
        #     since nginx uses the DNS server only for
        #     name resolution
        #   - Some DNS servers resolve localhost in A but
        #     not AAAA records (like Wikimedia's!). This too
        #     causes nginx to fail, since the AAAA returns
        #     NXDOMAIN, which makes nginx fail hard
        #   - Even when all of this works, it is slightly
        #     faster to just avoid the DNS lookup for something
        #     as trivial as looking up localhost
        if self.default_target:
            parts = urlsplit(self.default_target)
            self.default_target = urlunsplit(
                (parts[0],
                 parts[1].replace('localhost', '127.0.0.1'),
                 parts[2], parts[3], parts[4])
            )

        public_ssl = self.public_ssl_cert != ''
        api_ssl = self.api_ssl_cert != ''

        # '' means 'listen on all interfaces' in python / nodejs
        # So we take it in to be compatible
        # FIXME: check what this does for ipv6
        if self.public_ip == '':
            public_ip = '0.0.0.0'
        else:
            public_ip = self.public_ip

        if self.api_ip == '':
            api_ip = '0.0.0.0'
        else:
            api_ip = self.api_ip


        proxy_streams = parse_proxy_streams_string(self.proxy_streams)

        context = {
            'proxy_streams': proxy_streams,
            'dns_resolver': self.dns_resolver,
            'access_log_dest': self.access_log_dest(),
            'public_port': self.public_port,
            'public_ip': public_ip,
            'api_port': self.api_port,
            'api_ip': api_ip,
            'authtoken': self.auth_token,
            'default_target': self.default_target,
            'api_ssl': api_ssl,
            'public_ssl': public_ssl,
            'public_ssl_cert': self.public_ssl_cert,
            'public_ssl_key': self.public_ssl_key,
            'public_ssl_ciphers': self.public_ssl_ciphers,
            'public_ssl_dhparam': self.public_ssl_dhparam,
            'api_ssl_cert': self.api_ssl_cert,
            'api_ssl_key': self.api_ssl_key,
            'api_ssl_ciphers': self.api_ssl_ciphers,
            'api_ssl_dhparam': self.api_ssl_dhparam,
            'error_path': self.error_path,
            'error_target': self.error_target,
            'extra_public_nginx_config': self.extra_public_nginx_config,
            'client_max_body_size': self.client_max_body_size
        }
        return template.render(**context)

    def start(self):
        if self.config_file != '':
            self.load_config_file(self.config_file)
        conf = self.build_nginx_conf()
        with NamedTemporaryFile() as f:
            f.write(conf.encode('utf-8'))
            f.flush()
            os.execle(self.nginx_path, self.nginx_path, '-c', f.name, {})
