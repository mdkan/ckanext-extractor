# encoding: utf-8

import urllib
import urllib2
import re
import simplejson
import httplib
from ConfigParser import ConfigParser

from BeautifulSoup import BeautifulSoup
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from model import *
from extra_data import *

import os

opener = urllib2.build_opener(urllib2.HTTPCookieProcessor)

startdate = datetime(2005, 01, 01)
enddate = datetime.now()

#keys 
URL = u'url'
LOCALIDAD = u'localidad'
PARTIDO_JUDICIAL = u'partido judicial'
RESUMEN = u'resumen'
CANCELADO = u'cancelado'
ORGANO_JUDICIAL = u'órgano judicial'
PROCEDIMIENTO_JUDICIAL = u'procedimiento judicial'
TELEFONO = u'teléfono'
VALORACION = u'valoración'
DEPOSITO = u'depósito'
NIG = u'nig'
DIRECCION = u'dirección'
HORA = u'hora'
DIA = u'día'

#
cod_eviction = 'hipotecari'

class Crawler():

    def isAnImportantWord(self, phrase, wordlist):
        for w in wordlist:
            if w in phrase.lower():
                return True
        return False

    def connection(self, url):
        #print "Connecting to... " + url
        soup = None
        try:
            response = opener.open(url)
            data = response.read()
            soup = BeautifulSoup(data, convertEntities=BeautifulSoup.HTML_ENTITIES)
            soup.prettify()
            #print "Connection OK"
            return soup
        except:
            print "ERROR accessing..."
            print url
            return None

    def scrappList(self):
        configParser = ConfigParser()
        configParser.read('crawler.cfg')
        db_connection = configParser.get('database', 'db_connection')
        pagination = int(configParser.get('crawler', 'pagination'))
        data_url = configParser.get('crawler', 'data_url')

        engine = create_engine(db_connection, convert_unicode=True, pool_recycle=3600)

        self.session = sessionmaker(bind = engine)()

        for cpartido in cpartidos.keys():
            page = 1
            isfinalpage = False
            while not isfinalpage:
                isfinalpage = True
                params = {
                    'cfechaH': enddate.strftime('%d/%m/%Y'),
                    'cfechaD': startdate.strftime('%d/%m/%Y'),
                    'cpartido': cpartido,
                    'ctipo': 'INMU',
                    'primerElem': page,
                }

                evlisthtml = self.connection(data_url + '?' + urllib.urlencode(params))

                for ev in evlisthtml.findAll('tr'):
                    if (ev.has_key('class') and "vevent" in ev['class']):
                        cancelled = False
                        if ev.has_key('title'):
                            cancelled = True
                        isfinalpage = False
                        for evspan in ev.findAll('span'):
                            if (evspan.has_key('class') and "summary" in evspan['class']):
                                detailsurl = evspan.find('a')['href']
                                title = evspan.find('a').contents[0]
                        if self.isAnImportantWord(title, importantworddict):
                            eviction = self.scrappEviction(cpartido=cpartido, url=detailsurl, title=title, cancelled=cancelled)

                page += pagination

        self.session.commit()
        self.session.close()

    def scrappEviction(self, cpartido, url, title, cancelled):
        evicdict = {}

        evhtml = self.connection(url)
        if evhtml is not None:
            for det in evhtml.findAll('div'):
                if (det.has_key('class') and "fila" in det['class']):
                    for datum in det.findAll('div'):
                        if (datum.has_key('class') and "etiqueta" in datum['class']):
                            etiqueta = u''
                            try:
                                etiqueta = datum.contents[0].contents[0]
                            except:
                                etiqueta = datum.contents[0]
                            if etiqueta[-1] == ':':
                                etiqueta = etiqueta[:-1]
                        elif (datum.has_key('class') and "dato" in datum['class']):
                            dato = u''
                            try:
                                dato = datum.contents[0].contents[0]
                            except:
                                dato = datum.contents[0]

                    evicdict[etiqueta.lower()] = dato

            evicdict[URL] = url
            evicdict[PARTIDO_JUDICIAL] = cpartidos[cpartido]
            evicdict[RESUMEN] = title
            evicdict[CANCELADO] = cancelled

            #check valid 'Localidad'
            if not LOCALIDAD in evicdict or evicdict[LOCALIDAD] == '.':
                for municipio in municipios:
                    if municipio.lower() in title.lower():
                        evicdict[LOCALIDAD] = municipio
                        break

            if not LOCALIDAD in evicdict or not evicdict[LOCALIDAD] in municipios:
                evicdict[LOCALIDAD] = evicdict[PARTIDO_JUDICIAL]

            if not DIRECCION in evicdict:
                evicdict[DIRECCION] = ''

            if cod_eviction in evicdict[PROCEDIMIENTO_JUDICIAL]:
                print "Storing to DB --> %s" % url

                day, month, year = evicdict[DIA].split('/')
                hour, minute = evicdict[HORA].split(':')
     
                evicdate = datetime(int(year), int(month), int(day), int(hour), int(minute))

                cpartidolocation = self.session.query(Municipio).filter_by(nombre = evicdict[PARTIDO_JUDICIAL]).first()
                partidojudicial = self.session.query(PartidoJudicial).filter_by(municipio = cpartidolocation).first()
                if partidojudicial is None:
                    partidojudicial = PartidoJudicial(evicdict[PARTIDO_JUDICIAL], evicdict[ORGANO_JUDICIAL], evicdict[TELEFONO], cpartidolocation)
                    self.session.add(partidojudicial)
                    self.session.commit()

                evicval = evicdict[VALORACION][:-2].replace('.', '').replace(',', '.')
                evicdep = evicdict[DEPOSITO][:-2].replace('.', '').replace(',', '.')
                eviction = Desahucio(evicdate, evicdict[URL], float(evicval), evicdict[CANCELADO], float(evicdep),
                    evicdict[RESUMEN], evicdict[PROCEDIMIENTO_JUDICIAL], evicdict[DIRECCION], evicdict[NIG],
                    self.session.query(Municipio).filter_by(nombre = evicdict[LOCALIDAD]).first(), partidojudicial)

                self.session.add(eviction)
                self.session.commit()

    def start_transformation(self, context):
        self.scrappList()

    def create_db(self):
        configParser = ConfigParser()
        configParser.read('crawler.cfg')
        db_connection = configParser.get('database', 'db_connection')
        engine = create_engine(db_connection, convert_unicode=True, pool_recycle=3600)

        #destroying database schema
        print 'Dropping tables'
        Base.metadata.drop_all(bind = engine)

        #creating database schema
        print 'Creating tables'
        Base.metadata.create_all(bind = engine)

        #add municipality information
        session = sessionmaker(bind = engine)()

        for municipio in municipios:
            munidb = Municipio(municipio)
            session.add(munidb)

        session.commit()
        session.close()

