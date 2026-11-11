"""Inventaire multi-caméra isolé, sans Frigate ni caméra réseau."""
import json
import math
import time
import unittest
from unittest.mock import patch
import test_components_cameras as base

app=base.server

class OverviewTests(unittest.TestCase):
    setUp=base.ComponentsCameraTests.setUp
    tearDown=base.ComponentsCameraTests.tearDown
    request=base.ComponentsCameraTests.request
    def configure(self):
        config={'cameras':{key:{'friendly_name':key.title(),'enabled':key!='paused',
            'record':{'continuous':{'days':3}},'onvif':{'host':'192.168.50.20','user':'private-account','password':'private-fixture'},
            'ffmpeg':{'inputs':[{'path':'rtsp://private-fixture'}]}} for key in ('entry','garage','paused','absent')}}
        app.private_write(self.config,json.dumps(config))

    def listing(self):
        status,data=self.request('GET','/api/cameras',token=self.token)
        self.assertEqual(status,200);return json.loads(data)

    def test_distinct_states_single_sample_no_secrets_no_mutation(self):
        self.configure();before=self.config.read_bytes()
        with patch.object(app,'video_json',return_value={'service':{'last_updated':time.time()},'cameras':{'entry':{'camera_fps':5.5},'garage':{'camera_fps':0},'paused':{'camera_fps':10}}}) as video:
            values=self.listing()
        video.assert_called_once_with('/api/stats')
        self.assertEqual([c['status'] for c in values],['receiving','no_frames','disabled','unknown'])
        self.assertEqual([c['online'] for c in values],[True,False,False,False])
        self.assertEqual([c['fps'] for c in values],[5.5,0,None,None])
        self.assertEqual(values[0]['observed_at'],values[1]['observed_at']);self.assertIsNone(values[2]['observed_at'])
        self.assertEqual(before,self.config.read_bytes())
        for private in ('private-fixture','private-account','rtsp://','192.168.50.20'):self.assertNotIn(private,json.dumps(values))
        with app.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_unavailable_or_malformed_stats_do_not_invent_offline(self):
        self.configure()
        for response in (None,[],{'cameras':[]},{'cameras':{'entry':None}},{'cameras':{'entry':{'camera_fps':True}}},
                         {'cameras':{'entry':{'camera_fps':'5'}}},{'cameras':{'entry':{'camera_fps':-1}}},
                         {'cameras':{'entry':{'camera_fps':math.nan}}},{'cameras':{'entry':{'camera_fps':math.inf}}}):
            with self.subTest(response=response),patch.object(app,'video_json',return_value=response):
                values=self.listing();self.assertEqual(values[0]['status'],'unknown');self.assertIsNone(values[0]['observed_at'])
                self.assertEqual(values[2]['status'],'disabled')
        for error in (app.Problem('private failure',503),OSError('private failure'),ValueError('invalid JSON')):
            with patch.object(app,'video_json',side_effect=error):self.assertEqual(self.listing()[0]['status'],'unknown')

    def test_viewer_can_read_without_admin_controls_or_unauthenticated_access(self):
        self.configure();self.assertEqual(self.request('GET','/api/cameras')[0],401)
        with app.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token,csrf=app.make_session('reader')
        with patch.object(app,'video_json',return_value={'cameras':{}}):
            self.assertEqual(self.request('GET','/api/cameras',token=token)[0],200)
        with patch.object(app,'ptz_move') as ptz:
            self.assertEqual(self.request('POST','/api/camera/ptz',{'camera':'entry','action':'left'},token,csrf)[0],403)
            ptz.assert_not_called()

    def test_empty_catalog_never_queries_video(self):
        app.private_write(self.config,json.dumps({'cameras':{}}))
        with patch.object(app,'video_json') as video:self.assertEqual(self.listing(),[]);video.assert_not_called()

    def test_old_positive_measurement_is_never_online_and_timestamp_is_not_refreshed(self):
        self.configure();stamp=time.time()-3600
        payload={'service':{'last_updated':stamp},'cameras':{'entry':{'camera_fps':5},'paused':{'camera_fps':5}}}
        with patch.object(app,'video_json',return_value=payload):values=self.listing()
        self.assertEqual(values[0]['status'],'stale');self.assertFalse(values[0]['online'])
        self.assertIsNone(values[0]['fps']);self.assertEqual(values[0]['observed_at'],stamp)
        self.assertEqual(values[2]['status'],'disabled')

    def test_missing_invalid_future_and_boundary_timestamps(self):
        import cameras
        self.configure();now=time.time()
        for stamp in (None,True,'123',math.inf,now+60,0):
            payload={'service':{'last_updated':stamp},'cameras':{'entry':{'camera_fps':5}}}
            with patch.object(app,'video_json',return_value=payload):
                values=self.listing();self.assertEqual(values[0]['status'],'unknown');self.assertFalse(values[0]['online'])
        self.assertTrue(cameras.fresh_stats({'service':{'last_updated':now-90}},now))
        self.assertFalse(cameras.fresh_stats({'service':{'last_updated':now-90.01}},now))
