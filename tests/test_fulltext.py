"""Recherche dans le contenu : texte tiré des documents sans les interpréter, index à part, réponses limitées aux espaces de chacun."""
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from urllib.parse import quote

import test_spaces
import fulltext as content
import doc_fixture as fixture
import library

app = test_spaces.app


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)

    def read(self, name, data):
        (self.folder / name).write_bytes(data if isinstance(data, bytes) else data.encode())
        return content.extract(self.fd, name, os.path.splitext(name)[1].lower(), os.stat(self.folder / name))

    def test_text_is_drawn_from_every_kind_of_document(self):
        # Un mot coupé par sa mise en forme reste un mot ; deux paragraphes restent séparés ; l'en-tête est lu aussi.
        self.assertEqual(self.read('a.docx', fixture.docx('Bonjour à tous', 'Le préau & la dalle', header='Mairie fictive')), ('Bonjour à tous Le préau & la dalle Mairie fictive', 'text'))
        self.assertEqual(self.read('b.xlsx', fixture.xlsx('Dalle', 'Aciers HA12')), ('Dalle Aciers HA12', 'text'))
        # Les diapositives dans leur ordre : la 2 avant la 10.
        self.assertEqual(self.read('c.pptx', fixture.pptx(*[f'Vue {i}' for i in range(1, 12)]))[0], ' '.join(f'Vue {i}' for i in range(1, 12)))
        self.assertEqual(self.read('d.odt', fixture.odt('Compte rendu', 'Réunion de chantier')), ('Compte rendu Réunion de chantier', 'text'))
        self.assertEqual(self.read('e.ods', fixture.odt('Poste', 'Montant', kind='spreadsheet')), ('Poste Montant', 'text'))
        self.assertEqual(self.read('f.txt', 'Texte simple, été'), ('Texte simple, été', 'text'))
        self.assertEqual(self.read('g.txt', 'Ancien fichier, été'.encode('cp1252')), ('Ancien fichier, été', 'text'))
        self.assertEqual(self.read('h.txt', '﻿Avec marque'.encode('utf-8')), ('Avec marque', 'text'))
        self.assertEqual(self.read('i.txt', 'Seize bits'.encode('utf-16')), ('Seize bits', 'text'))
        self.assertEqual(self.read('j.html', '<html><head><style>p{color:red}</style><SCRIPT>secret()</SCRIPT></head><body><h1>Titre</h1><p>Corps &eacute;crit</p><!-- cache --></body></html>'),
                         ('Titre Corps écrit', 'text'))
        # Rien à lire, binaire, trop gros, dossier compressé qui n'en est pas un, lien : jamais d'erreur, un état.
        self.assertEqual(self.read('k.txt', ''), ('', 'empty'))
        self.assertEqual(self.read('l.txt', b'\x00\x01\x02binaire'), ('', 'skipped'))
        self.assertEqual(self.read('m.docx', b'pas une archive'), ('', 'failed'))
        with unittest.mock.patch.object(content, 'TEXT_MAX', 10):
            self.assertEqual(self.read('n.txt', 'bien plus que dix octets'), ('', 'big'))
        (self.folder / 'o.txt').symlink_to(self.folder / 'f.txt')
        self.assertEqual(content.extract(self.fd, 'o.txt', '.txt', os.stat(self.folder / 'f.txt')), ('', 'failed'))
        self.assertEqual(self.read('p.txt', 'x' * (content.BODY_MAX + 500))[0], 'x' * content.BODY_MAX)

    def test_markup_is_never_interpreted(self):
        hostile = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "file:///etc/passwd"><!ENTITY big "aaaaaaaaaa">]><d><p>avant &xxe; &big; apr&#232;s</p><![CDATA[brut]]></d>'
        text = ' '.join(content.plain(hostile).split())
        # Une entité déclarée par le document n'est ni suivie ni développée : elle reste telle qu'écrite.
        self.assertIn('avant &xxe; &big; après', text)
        self.assertNotIn('root:', text); self.assertNotIn('aaaaaaaaaa', text); self.assertIn('brut', text)
        self.assertEqual(' '.join(content.plain('<w:p><w:r><w:t>Bon</w:t></w:r><w:r><w:t>jour</w:t></w:r></w:p><w:p><w:t>monde</w:t></w:p>').split()), 'Bonjour monde')
        self.assertEqual(' '.join(content.plain('a<!-- jamais refermé b', page=True).split()), 'a')
        self.assertEqual(' '.join(content.plain('a<script>b', page=True).split()), 'a')
        self.assertEqual(' '.join(content.plain('1 < 2 et 3 > 2').split()), '1 2 et 3 2')
        # Entrées faites pour coûter cher : chacune se traite d'un seul balayage.
        started = time.monotonic()
        for trap in ('<!--' * 400000, '<script' * 300000, '<' * 1500000, '<a ' * 500000, '&' * 1500000, '<![CDATA[' * 200000):
            content.plain(trap, page=True)
        self.assertLess(time.monotonic() - started, 8)

    def test_a_trapped_archive_costs_neither_memory_nor_time(self):
        # Partie qui se décompresse en bien plus qu'annoncé permis : la lecture s'arrête au plafond.
        bomb = self.folder / 'bombe.docx'
        with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as pack:
            pack.writestr('word/document.xml', b'<w:t>' + b'a' * (40 * 1024 ** 2))
        with unittest.mock.patch.object(content, 'MEMBER_MAX', 1024 ** 2):
            started = time.monotonic()
            self.assertEqual(content.extract(self.fd, 'bombe.docx', '.docx', os.stat(bomb)), ('', 'empty'))
            self.assertLess(time.monotonic() - started, 3)
        # Partie chiffrée, trop de parties : laissées de côté.
        locked = self.folder / 'verrou.docx'
        with zipfile.ZipFile(locked, 'w') as pack:
            pack.writestr('word/document.xml', '<w:t>secret</w:t>')
        raw = bytearray(locked.read_bytes())
        for at in (raw.find(b'PK\x03\x04') + 6, raw.find(b'PK\x01\x02') + 8):
            raw[at] |= 1
        locked.write_bytes(bytes(raw))
        self.assertEqual(content.extract(self.fd, 'verrou.docx', '.docx', os.stat(locked)), ('', 'empty'))
        many = self.folder / 'foule.pptx'
        with zipfile.ZipFile(many, 'w') as pack:
            for index in range(5001):
                pack.writestr(f'ppt/slides/slide{index}.xml', '<a:t>x</a:t>')
        self.assertEqual(content.extract(self.fd, 'foule.pptx', '.pptx', os.stat(many)), ('', 'empty'))

    def tool(self, script):
        path = self.folder / 'lecteur-pdf'
        path.write_text('#!/bin/sh\n' + script + '\n')
        path.chmod(0o700)
        return unittest.mock.patch.object(content, 'reader', return_value=str(path))

    def test_pdf_goes_through_a_bounded_tool_or_waits_for_one(self):
        with unittest.mock.patch.object(content, 'reader', return_value=None):
            self.assertEqual(self.read('a.pdf', fixture.pdf('Facture 0042')), ('', 'nopdf'))
        # L'outil reçoit le fichier sur son entrée, jamais son chemin ; ce qu'il écrit devient le texte.
        with self.tool('test "$7" = "-" && test "$8" = "-" && test "$(head -c 5)" = "%PDF-" && printf "Texte   lu\\npar l outil"'):
            self.assertEqual(self.read('b.pdf', fixture.pdf('Facture 0042')), ('Texte lu par l outil', 'text'))
        # Outil qui échoue : rien n'est gardé. Outil qui ne finit pas : il est arrêté.
        with self.tool('printf "à moitié"; exit 3'):
            self.assertEqual(self.read('c.pdf', fixture.pdf('x')), ('', 'empty'))
        with self.tool('sleep 30'), unittest.mock.patch.object(content, 'SECONDS', 1):
            started = time.monotonic()
            self.assertEqual(self.read('d.pdf', fixture.pdf('x')), ('', 'empty'))
            self.assertLess(time.monotonic() - started, 6)

    @unittest.skipUnless(shutil.which('pdftotext'), 'pdftotext absent de cette machine')
    def test_real_pdf_tool_reads_a_page(self):
        self.assertEqual(self.read('vrai.pdf', fixture.pdf('Facture 0042', 'Béton pour le préau')), ('Facture 0042 Béton pour le préau', 'text'))
        self.assertEqual(self.read('faux.pdf', b'%PDF-1.4 rien de valide'), ('', 'empty'))


class SearchTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home'))

    def team(self):
        content.SCAN.stop()
        content.SCAN = library.Scanner(content.work, fresh=0)
        self.addCleanup(content.SCAN.stop)
        patch = unittest.mock.patch.object(content, 'reader', return_value=None)   # les PDF ont leur propre essai : ici, le même résultat sur toute machine
        patch.start(); self.addCleanup(patch.stop)
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.team_dir = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        self.mine = self.home('camille')
        self.mine_dir = Path(app.ROOT) / 'data/espaces' / self.mine[7:]
        self.mine_dir.mkdir(parents=True, exist_ok=True)
        self.common = Path(app.ROOT) / 'data/fichiers'

    def found(self, who, words, extra=''):
        """Résultats après un parcours complet : une première demande le lance, on l'attend, la seconde le lit."""
        address = '/api/files/content?q=' + quote(words) + extra
        content.SCAN.fresh = 0
        self.get(who, address)
        content.SCAN.wait()
        content.SCAN.fresh = 3600
        return self.get(who, address)

    def names(self, who, words, extra=''):
        status, data = self.found(who, words, extra)
        return sorted(item['name'] for item in data['items']) if status == 200 else status

    def test_a_document_is_found_by_what_it_says_only_where_the_person_may_read(self):
        self.team()
        (self.team_dir / 'Réunions').mkdir()
        (self.team_dir / 'Réunions/compte-rendu.docx').write_bytes(fixture.docx('La dalle du préau sera coulée en novembre', 'Réception des aciers le 12'))
        (self.team_dir / 'budget.xlsx').write_bytes(fixture.xlsx('Préau', 'Dalle béton', '12 500'))
        (self.mine_dir / 'journal.md').write_text('# Journal\n\nPenser au préau avant la rentrée.')
        (self.common / 'reglement.odt').write_bytes(fixture.odt('Règlement intérieur', 'Le préau est ouvert de 8 h à 18 h'))
        (self.common / 'sans-rapport.txt').write_text('Rien à voir ici')
        (self.common / 'image.png').write_bytes(b'\x89PNG pr\xc3\xa9au')
        (self.common / '.cache').mkdir(); (self.common / '.cache/cache.txt').write_text('préau caché')
        (self.common / 'lien.txt').symlink_to(self.mine_dir / 'journal.md')
        status, data = self.found('camille', 'préau')
        self.assertEqual((status, data['scan']['error'], data['scan']['partial'], data['partial']), (200, None, None, False))
        self.assertEqual(sorted((i['area'], i['path'], i['name']) for i in data['items']),
                         sorted([(self.space, 'Réunions', 'compte-rendu.docx'), (self.space, '', 'budget.xlsx'), (self.mine, '', 'journal.md'), ('fichiers', '', 'reglement.odt')]))
        self.assertEqual((data['read'], data['words'], data['limit'], data['pdf']), (5, ['préau'], content.RESULTS, False))
        # L'extrait entoure le mot trouvé de deux marques que la page transforme elle-même : aucune balise ne vient du serveur.
        extract = next(i['extract'] for i in data['items'] if i['name'] == 'reglement.odt')
        self.assertIn('Le \x02préau\x03 est ouvert', extract); self.assertNotIn('<', extract)
        item = next(i for i in data['items'] if i['name'] == 'compte-rendu.docx')
        self.assertEqual((item['directory'], item['link'], item['size'] > 0, item['modified'] > 1e9), (False, False, True, True))
        # Sans accent, en majuscules, par le début du mot, plusieurs mots à la fois, par le nom du fichier.
        self.assertEqual(self.names('camille', 'PREAU'), ['budget.xlsx', 'compte-rendu.docx', 'journal.md', 'reglement.odt'])
        self.assertEqual(self.names('camille', 'coul nov'), ['compte-rendu.docx'])
        self.assertEqual(self.names('camille', 'aciers préau'), ['compte-rendu.docx'])
        self.assertEqual(self.names('camille', 'reglement'), ['reglement.odt'])
        self.assertEqual(self.names('camille', 'introuvable'), [])
        self.assertEqual(self.names('camille', '12 500'), ['budget.xlsx'])
        # Chacun ne trouve que dans ses espaces : ni l'espace personnel d'un autre, ni une équipe dont on n'est pas.
        self.assertEqual(self.names('bruno', 'préau'), ['budget.xlsx', 'compte-rendu.docx', 'reglement.odt'])
        self.assertEqual(self.names('dora', 'préau'), ['reglement.odt'])
        self.assertEqual(self.names('lecteur', 'préau'), ['reglement.odt'])
        self.assertEqual(self.names('admin', 'préau'), ['budget.xlsx', 'compte-rendu.docx', 'reglement.odt'])
        self.assertEqual(self.names('admin', 'rentrée'), [])
        self.assertEqual(self.request('GET', '/api/files/content?q=preau')[0], 401)
        # Un seul espace, à condition d'y avoir droit.
        self.assertEqual(self.names('camille', 'préau', f'&area={self.space}'), ['budget.xlsx', 'compte-rendu.docx'])
        for who, area in (('dora', self.space), ('bruno', self.mine), ('admin', self.mine), ('camille', 'video'), ('camille', 'inconnu')):
            self.assertEqual(self.get(who, f'/api/files/content?q=preau&area={area}')[0], 403, (who, area))
        # Ce que l'on tape ne devient jamais un opérateur de la recherche : au pire rien n'est trouvé, jamais d'erreur.
        for odd in ('"préau', 'préau"', 'préau*', 'préau OR rentrée', 'NEAR(préau dalle)', 'name:préau', '-préau', 'préau AND', '(préau', "préau' OR 1=1 --", 'préau;DROP TABLE docs', '^préau', 'pré\x00au'):
            status, data = self.get('camille', '/api/files/content?q=' + quote(odd))
            self.assertEqual(status, 200, odd)
        self.assertEqual(self.names('camille', 'préau OR rentrée'), [])
        self.assertEqual(self.names('dora', 'name:rentrée'), [])
        for bad in ('', 'a', '*', '" "', 'x' * 81):
            self.assertEqual(self.get('camille', '/api/files/content?q=' + quote(bad))[0], 400, bad)
        # L'index vit à part : la base de Nacre n'a pas changé de forme.
        self.assertTrue((Path(app.STATE) / 'search.db').is_file())
        with app.database() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name IN ('docs','texts')").fetchone())

    def test_index_follows_changes_and_never_reads_twice_what_did_not_change(self):
        self.team()
        (self.team_dir / 'note.txt').write_text('Livraison des aciers mardi')
        (self.team_dir / 'plan.txt').write_text('Plan de coffrage')
        self.assertEqual(self.names('camille', 'aciers'), ['note.txt'])
        # Rien n'a changé : aucun fichier n'est rouvert.
        with unittest.mock.patch.object(content, 'extract', wraps=content.extract) as reread:
            self.assertEqual(self.names('camille', 'aciers'), ['note.txt'])
            self.assertEqual(reread.call_count, 0)
        # Document réécrit : l'ancien texte n'est plus trouvé, le nouveau l'est. Document retiré : oublié.
        (self.team_dir / 'note.txt').write_text('Livraison du béton jeudi matin')
        (self.team_dir / 'plan.txt').unlink()
        self.assertEqual((self.names('camille', 'aciers'), self.names('camille', 'béton'), self.names('camille', 'coffrage')), ([], ['note.txt'], []))
        # Un PDF laissé de côté faute d'outil est repris quand l'outil arrive, sans que le fichier ait changé.
        (self.team_dir / 'facture.pdf').write_bytes(fixture.pdf('Facture 0042'))
        self.assertEqual(self.names('camille', 'facture'), ['facture.pdf'])     # par son nom seulement
        self.assertEqual(self.names('camille', 'virement'), [])
        tool = Path(app.ROOT) / 'lecteur-pdf'
        tool.write_text('#!/bin/sh\ncat >/dev/null\nprintf "Virement attendu sous trente jours"\n'); tool.chmod(0o700)
        with unittest.mock.patch.object(content, 'reader', return_value=str(tool)):
            status, data = self.found('camille', 'virement')
            self.assertEqual(([i['name'] for i in data['items']], data['pdf']), (['facture.pdf'], True))
        # Espace vidé puis supprimé : plus rien n'en sort, l'index l'oublie.
        for path in list(self.team_dir.iterdir()):
            path.unlink()
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 200)
        self.assertEqual(self.names('camille', 'béton'), [])
        with sqlite3.connect(Path(app.STATE) / 'search.db') as db:
            self.assertEqual((db.execute('SELECT count(*) FROM docs').fetchone()[0], db.execute('SELECT count(*) FROM texts').fetchone()[0]), (0, 0))
        # Index effacé ou d'une autre forme : il se reconstruit.
        (self.mine_dir / 'seul.txt').write_text('Un seul document')
        self.assertEqual(self.names('camille', 'document'), ['seul.txt'])
        content.SCAN.wait()
        with sqlite3.connect(Path(app.STATE) / 'search.db') as db:
            db.execute('DROP TABLE texts'); db.execute('PRAGMA user_version=77')
        self.assertEqual(self.names('camille', 'document'), ['seul.txt'])

    def test_an_oversized_space_stops_at_its_limit_without_starving_the_others(self):
        self.team()
        for index in range(6):
            (self.mine_dir / f'grand-{index}.txt').write_text('chantier du grand espace')
        (self.team_dir / 'equipe.txt').write_text('chantier de l equipe')
        (self.common / 'commun.txt').write_text('chantier commun')
        with unittest.mock.patch.object(library, 'VISITED', 4):
            status, data = self.found('camille', 'chantier')
            names = sorted(i['name'] for i in data['items'])
            self.assertEqual((status, data['scan']['partial'], data['scan']['error']), (200, 'count', None))
            self.assertEqual(len([n for n in names if n.startswith('grand-')]), 4)
            self.assertIn('equipe.txt', names); self.assertIn('commun.txt', names)
            self.assertEqual(self.names('camille', 'chantier'), names)
        self.assertEqual(len(self.names('camille', 'chantier')), 8)

    def test_results_are_bounded_and_a_system_without_the_engine_says_so(self):
        self.team()
        for index in range(content.RESULTS + 5):
            (self.common / f'fiche-{index:03d}.txt').write_text(f'Fiche de chantier numéro {index}')
        status, data = self.found('camille', 'chantier')
        self.assertEqual((status, len(data['items']), data['partial'], data['read']), (200, content.RESULTS, True, content.RESULTS + 5))
        # Moteur de base de données sans index de texte : dit clairement, jamais une erreur brute.
        with unittest.mock.patch.object(library, 'index', side_effect=sqlite3.OperationalError('no such module: fts5')):
            status, data = self.get('camille', '/api/files/content?q=chantier')
        self.assertEqual(status, 501); self.assertIn('n’est pas disponible sur ce système', data['error'])


if __name__ == '__main__':
    unittest.main()
