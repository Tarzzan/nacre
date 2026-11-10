"""Petit serveur SMTP de test, limité au loopback, jamais utilisé par Nacre."""
from pathlib import Path
import socketserver
import ssl
import subprocess
import threading


def certificate(directory):
    cert=Path(directory)/'smtp-cert.pem';key=Path(directory)/'smtp-key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    return cert,context


class Handler(socketserver.StreamRequestHandler):
    def reply(self,text):self.wfile.write((text+'\r\n').encode());self.wfile.flush()
    def handle(self):
        secure=self.server.direct
        self.request.settimeout(5)
        try:
            self.reply('220 local-fixture ESMTP')
            while True:
                line=self.rfile.readline(65536)
                if not line:return
                verb=line.split(b' ',1)[0].strip().upper()
                self.server.commands.append((verb.decode(),secure))
                if verb in (b'EHLO',b'HELO'):
                    self.reply('250-local-fixture')
                    if not secure and self.server.allow_starttls:self.reply('250-STARTTLS')
                    self.reply('250 AUTH PLAIN')
                elif verb==b'STARTTLS':
                    if not self.server.allow_starttls:self.reply('502 unavailable');continue
                    self.reply('220 Ready')
                    self.connection=self.server.context.wrap_socket(self.connection,server_side=True)
                    self.rfile.close();self.wfile.close()
                    self.rfile=self.connection.makefile('rb');self.wfile=self.connection.makefile('wb');secure=True
                elif verb==b'AUTH':self.reply(str(self.server.auth_code)+' fixture-auth-private-text')
                elif verb==b'MAIL':self.reply('250 OK')
                elif verb==b'RCPT':self.reply(str(self.server.rcpt_code)+' fixture-recipient-private-text')
                elif verb==b'DATA':
                    self.reply('354 Send data');body=[]
                    while True:
                        part=self.rfile.readline(65536)
                        if part in (b'.\r\n',b''):break
                        body.append(part[1:] if part.startswith(b'..') else part)
                    code=self.server.data_codes.pop(0) if self.server.data_codes else 250
                    self.server.received.append({'data':b''.join(body),'secure':secure,'status':code})
                    self.reply(str(code)+' fixture-data-private-text')
                    if self.server.drop_after_data:return
                elif verb==b'QUIT':self.reply('221 Bye');return
                elif verb==b'RSET':self.reply('250 OK')
                else:self.reply('502 Unsupported')
        except (OSError,ValueError):pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    def __init__(self,context,direct=False,port=0):
        self.context=context;self.direct=direct;self.allow_starttls=True;self.auth_code=235;self.rcpt_code=250
        self.data_codes=[];self.drop_after_data=False;self.commands=[];self.received=[]
        super().__init__(('127.0.0.1',port),Handler)
    def get_request(self):
        sock,address=super().get_request();sock.settimeout(5)
        if self.direct:
            try:sock=self.context.wrap_socket(sock,server_side=True)
            except OSError:sock.close();raise
        return sock,address
    def start(self):
        self.thread=threading.Thread(target=self.serve_forever,daemon=True);self.thread.start();return self
    def stop(self):self.shutdown();self.server_close();self.thread.join(2)
