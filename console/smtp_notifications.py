"""Notifications email : un destinataire, TLS obligatoire, erreurs sans secrets."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import ipaddress
import re
import smtplib
import ssl


def defaults():
    return {'host':'','port':587,'security':'starttls','username':'','password':'','sender':'','recipient':''}


def mailbox(value):
    if not isinstance(value,str) or len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+",value):return False
    local,domain=value.rsplit('@',1)
    return len(local)<=64 and not local.startswith('.') and not local.endswith('.') and '..' not in local and hostname(domain)


def hostname(value):
    if not isinstance(value,str) or not value or len(value)>253:return False
    try:ipaddress.ip_address(value);return True
    except ValueError:pass
    return all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',part) for part in value.split('.'))


def configure(app, body, old):
    source=body.get('smtp')
    if not isinstance(source,dict):raise app.Problem('Renseignez la configuration SMTP.')
    value={key:source.get(key) for key in ('host','port','security','username','sender','recipient')}
    if not hostname(value['host']) or type(value['port']) is not int or not 1<=value['port']<=65535 or value['security'] not in ('starttls','tls'):
        raise app.Problem('Serveur, port ou chiffrement SMTP invalide. STARTTLS ou TLS direct est obligatoire.')
    if not mailbox(value['sender']) or not mailbox(value['recipient']):
        raise app.Problem('Renseignez une seule adresse email ASCII pour l’expéditeur et le destinataire, sans nom affiché.')
    password=source.get('password','');clear=source.get('clear_password',False)
    if not isinstance(value['username'],str) or len(value['username'])>320 or any(ord(c)<32 or ord(c)>126 for c in value['username']):
        raise app.Problem('Compte SMTP invalide.')
    if not isinstance(password,str) or len(password)>4096 or any(ord(c)<32 or ord(c)>126 for c in password) or type(clear) is not bool or (password and clear):
        raise app.Problem('Mot de passe SMTP invalide ; choisissez de le remplacer ou de le supprimer.')
    if old['password'] and any(value[k]!=old[k] for k in ('host','port','security','username')) and not password and not clear:
        raise app.Problem('Pour changer de serveur ou de compte, renseignez le mot de passe adapté ou supprimez celui enregistré.')
    value['password']='' if clear else password or old['password']
    if bool(value['username'])!=bool(value['password']):raise app.Problem('Le compte et le mot de passe SMTP doivent être renseignés ensemble, ou tous deux laissés vides pour un relais sans authentification.')
    return value


def deliver(config, item):
    smtp=None
    try:
        labels={'opened':'Incident détecté','updated':'Incident actualisé','resolved':'Retour à la normale','test':'Test'}
        occurred=datetime.fromtimestamp(item['created'],timezone.utc)
        message=EmailMessage()
        message['From']=config['sender'];message['To']=config['recipient']
        message['Subject']='[Nacre] '+labels[item['event']]+' · '+item['title']
        message['Date']=format_datetime(occurred)
        message['Message-ID']='<'+item['id']+'@nacre.local>'
        message['X-Nacre-Event-Id']=item['id']
        message.set_content(labels[item['event']]+'\n'+item['title']+'\n\n'+item['message']+'\n\nÉvénement : '+occurred.isoformat()+'\nGravité : '+item['severity']+'\n')
        context=ssl.create_default_context()
        options={'host':config['host'],'port':config['port'],'timeout':10,'local_hostname':'nacre.local'}
        smtp=smtplib.SMTP_SSL(context=context,**options) if config['security']=='tls' else smtplib.SMTP(**options)
        code,text=smtp.ehlo()
        if code!=250:raise smtplib.SMTPHeloError(code,text)
        if config['security']=='starttls':
            smtp.starttls(context=context)
            code,text=smtp.ehlo()
            if code!=250:raise smtplib.SMTPHeloError(code,text)
        if config['username']:smtp.login(config['username'],config['password'])
        refused=smtp.send_message(message,from_addr=config['sender'],to_addrs=[config['recipient']])
        if refused:raise smtplib.SMTPRecipientsRefused(refused)
        return True,False,'Accepté par le serveur SMTP ; remise en boîte non confirmée.'
    except smtplib.SMTPRecipientsRefused as error:
        code=next(iter(error.recipients.values()))[0]
        return False,400<=code<500,'Destinataire refusé (SMTP '+str(code)+').'
    except smtplib.SMTPResponseException as error:
        return False,400<=error.smtp_code<500,'Refus du serveur SMTP ('+str(error.smtp_code)+').'
    except smtplib.SMTPNotSupportedError:
        return False,False,'Le serveur ne propose pas le chiffrement ou l’authentification requis.'
    except (OSError,smtplib.SMTPServerDisconnected):
        return False,True,'Connexion SMTP impossible, délai dépassé ou certificat TLS non valide.'
    except Exception:
        return False,False,'Envoi SMTP impossible ; vérifiez la configuration.'
    finally:
        if smtp is not None:
            # Un échec de QUIT après DATA accepté ne doit pas renvoyer l'email.
            try:smtp.quit()
            except Exception:pass
            smtp.close()
