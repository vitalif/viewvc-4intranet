#
# Copyright (C) 1999-2009 The ViewCVS Group. All Rights Reserved.
#
# By using this file, you agree to the terms and conditions set forth in
# the LICENSE.html file which can be found at the top level of the ViewVC
# distribution or at http://viewvc.org/license-1.html.
#
# For more information, visit http://viewvc.org/
#
# -----------------------------------------------------------------------

import os
import sys
import string
import time
import re
import cgi

import vclib
import dbi

## Current commits database schema version number.
##
## Version 0 was the original Bonsai-compatible version.
##
## Version 1 added the 'metadata' table (which holds the 'version' key)
## and renamed all the 'repository'-related stuff to be 'root'-
##
CURRENT_SCHEMA_VERSION = 1

## error
error = "cvsdb error"

## CheckinDatabase provides all interfaces needed to the SQL database
## back-end; it needs to be subclassed, and have its "Connect" method
## defined to actually be complete; it should run well off of any DBI 2.0
## complient database interface

class CheckinDatabase:
    def __init__(self, cfg, guesser, readonly, request = None):
        self.cfg = cfg
        self.guesser = guesser
        self.readonly = readonly
        self.request = request

        self._host      = cfg.host
        self._port      = cfg.port
        self._socket    = cfg.socket
        self._user      = readonly and cfg.user or cfg.readonly_user
        self._passwd    = readonly and cfg.passwd or cfg.readonly_passwd
        self._database  = cfg.database_name
        self._row_limit = cfg.row_limit
        self._version   = None
        self._min_relevance = cfg.fulltext_min_relevance

        # Sphinx settings
        self.index_content = cfg.index_content
        self.content_max_size = cfg.content_max_size
        if self.content_max_size > 4*1024*1024 or self.content_max_size <= 0:
            self.content_max_size = 4*1024*1024
        self.enable_snippets = cfg.enable_snippets
        self.sphinx_host = cfg.sphinx_host
        self.sphinx_port = cfg.sphinx_port
        self.sphinx_socket = cfg.sphinx_socket
        self.sphinx_index = cfg.sphinx_index

        # Snippet settings
        self.snippet_options = {}
        for i in cfg.sphinx_snippet_options.split('\n'):
            i = i.split(':', 1)
            if len(i) == 2:
                (a, b) = i
                if b[0] == ' ':
                    b = b[1:]
                b = b.replace('\\n', '\n')
                if re.match('\d+', b):
                    b = int(b)
                self.snippet_options[a] = b
        self.snippet_options_str = ''.join(', %s AS '+i for i in self.snippet_options)
        self.preformatted_mime = cfg.sphinx_preformatted_mime
        if 'before_match' in self.snippet_options:
            self.snippet_beforematch_html = cgi.escape(self.snippet_options['before_match'])
        if 'after_match' in self.snippet_options:
            self.snippet_aftermatch_html = cgi.escape(self.snippet_options['after_match'])

        ## database lookup caches
        self._get_cache = {}
        self._get_id_cache = {}
        self._desc_id_cache = {}

        # Sphinx connection None by default
        self.sphinx = None

    def Connect(self):
        self.db = dbi.connect(
            self._host, self._port, self._socket, self._user, self._passwd, self._database)
        cursor = self.db.cursor()
        cursor.execute("SET AUTOCOMMIT=1")
        table_list = self.GetTableList()
        if 'metadata' in table_list:
            version = self.GetMetadataValue("version")
            if version is None:
                self._version = 0
            else:
                self._version = int(version)
        else:
            self._version = 0
        if self._version > CURRENT_SCHEMA_VERSION:
            raise DatabaseVersionError("Database version %d is newer than the "
                                       "last version supported by this "
                                       "software." % (self._version))
        if self.index_content:
            self.sphinx = dbi.connect(self.sphinx_host, self.sphinx_port, self.sphinx_socket, '', '', '')

    def utf8(self, value):
        return self.guesser.utf8(value)

    def sql_get_id(self, table, column, value, auto_set):
        value = self.utf8(value)

        sql = "SELECT id FROM %s WHERE %s=%%s" % (table, column)
        sql_args = (value, )

        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        try:
            (id, ) = cursor.fetchone()
        except TypeError:
            if not auto_set:
                return None
        else:
            return str(int(id))

        ## insert the new identifier
        sql = "INSERT INTO %s(%s) VALUES(%%s)" % (table, column)
        sql_args = (value, )
        cursor.execute(sql, sql_args)

        return self.sql_get_id(table, column, value, 0)

    def get_id(self, table, column, value, auto_set):
        ## attempt to retrieve from cache
        try:
            return self._get_id_cache[table][column][value]
        except KeyError:
            pass

        id = self.sql_get_id(table, column, value, auto_set)
        if id == None:
            return None

        ## add to cache
        try:
            temp = self._get_id_cache[table]
        except KeyError:
            temp = self._get_id_cache[table] = {}

        try:
            temp2 = temp[column]
        except KeyError:
            temp2 = temp[column] = {}

        temp2[value] = id
        return id

    def sql_get(self, table, column, id):
        sql = "SELECT %s FROM %s WHERE id=%%s" % (column, table)
        sql_args = (id, )

        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        try:
            (value, ) = cursor.fetchone()
        except TypeError:
            return None

        return value

    def get(self, table, column, id):
        ## attempt to retrieve from cache
        try:
            return self._get_cache[table][column][id]
        except KeyError:
            pass

        value = self.sql_get(table, column, id)
        if value == None:
            return None

        ## add to cache
        try:
            temp = self._get_cache[table]
        except KeyError:
            temp = self._get_cache[table] = {}

        try:
            temp2 = temp[column]
        except KeyError:
            temp2 = temp[column] = {}

        temp2[id] = value
        return value

    def get_list(self, table, field_index):
        sql = "SELECT * FROM %s" % (table)
        cursor = self.db.cursor()
        cursor.execute(sql)

        list = []
        while 1:
            row = cursor.fetchone()
            if row == None:
                break
            list.append(row[field_index])

        return list

    def GetTableList(self):
        sql = "SHOW TABLES"
        cursor = self.db.cursor()
        cursor.execute(sql)
        list = []
        while 1:
            row = cursor.fetchone()
            if row == None:
                break
            list.append(row[0])
        return list

    def GetMetadataValue(self, name):
        sql = "SELECT value FROM metadata WHERE name=%s"
        sql_args = (name)
        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        try:
            (value,) = cursor.fetchone()
        except TypeError:
            return None
        return value

    def SetMetadataValue(self, name, value):
        assert(self._version > 0)
        sql = "REPLACE INTO metadata (name, value) VALUES (%s, %s)"
        sql_args = (name, value)
        cursor = self.db.cursor()
        try:
            cursor.execute(sql, sql_args)
        except Exception, e:
            raise Exception("Error setting metadata: '%s'\n"
                            "\tname  = %s\n"
                            "\tvalue = %s\n"
                            % (str(e), name, value))

    def GetBranchID(self, branch, auto_set = 1):
        return self.get_id("branches", "branch", branch, auto_set)

    def GetBranch(self, id):
        return self.get("branches", "branch", id)

    def GetDirectoryID(self, dir, auto_set = 1):
        return self.get_id("dirs", "dir", dir, auto_set)

    def GetDirectory(self, id):
        return self.get("dirs", "dir", id)

    def GetFileID(self, file, auto_set = 1):
        return self.get_id("files", "file", file, auto_set)

    def GetFile(self, id):
        return self.get("files", "file", id)

    def GetAuthorID(self, author, auto_set = 1):
        return self.get_id("people", "who", author, auto_set)

    def GetAuthor(self, id):
        return self.get("people", "who", id)

    def GetRepositoryID(self, repository, auto_set = 1):
        return self.get_id("repositories", "repository", repository, auto_set)

    def GetRepository(self, id):
        return self.get("repositories", "repository", id)

    def GetRepositoryList(self):
        return self.get_list("repositories", repository)

    def SQLGetDescriptionID(self, description, auto_set = 1):
        description = self.utf8(description)
        ## lame string hash, blame Netscape -JMP
        hash = len(description)

        sql = "SELECT id FROM descs WHERE hash=%s AND description=%s"
        sql_args = (hash, description)

        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        try:
            (id, ) = cursor.fetchone()
        except TypeError:
            if not auto_set:
                return None
        else:
            return str(int(id))

        sql = "INSERT INTO descs (hash,description) values (%s,%s)"
        sql_args = (hash, description)
        cursor.execute(sql, sql_args)

        return self.GetDescriptionID(description, 0)

    def GetDescriptionID(self, description, auto_set = 1):
        ## attempt to retrieve from cache
        hash = len(description)
        try:
            return self._desc_id_cache[hash][description]
        except KeyError:
            pass

        id = self.SQLGetDescriptionID(description, auto_set)
        if id == None:
            return None

        ## add to cache
        try:
            temp = self._desc_id_cache[hash]
        except KeyError:
            temp = self._desc_id_cache[hash] = {}

        temp[description] = id
        return id

    def GetDescription(self, id):
        return self.get("descs", "description", id)

    def GetRepositoryList(self):
        return self.get_list("repositories", 1)

    def GetBranchList(self):
        return self.get_list("branches", 1)

    def GetAuthorList(self):
        return self.get_list("people", 1)

    def GetLatestCheckinTime(self, repository):
        repository_id = self.GetRepositoryID(repository.rootpath, 0)
        if repository_id is None:
            return None

        commits_table = self._version >= 1 and 'commits' or 'checkins'
        sql = "SELECT ci_when FROM %s WHERE "\
              "repositoryid = %%s ORDER BY ci_when DESC LIMIT 1" % (commits_table)
        sql_args = (repository_id)

        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        ci_when = None
        try:
            ci_when = cursor.fetchone()[0]
        except TypeError:
            return None

        return dbi.TicksFromDateTime(ci_when)

    def AddCommitList(self, commit_list):
        for commit in commit_list:
            self.AddCommit(commit)

    def AddCommit(self, commit):
        props = {
            'type'         : commit.GetTypeString(),
            'ci_when'      : dbi.DateTimeFromTicks(commit.GetTime() or 0.0),
            'whoid'        : self.GetAuthorID(commit.GetAuthor()),
            'repositoryid' : self.GetRepositoryID(commit.GetRepository()),
            'dirid'        : self.GetDirectoryID(commit.GetDirectory()),
            'fileid'       : self.GetFileID(commit.GetFile()),
            'revision'     : commit.GetRevision(),
            'branchid'     : self.GetBranchID(commit.GetBranch()),
            'addedlines'   : commit.GetPlusCount() or '0',
            'removedlines' : commit.GetMinusCount() or '0',
            'descid'       : self.GetDescriptionID(commit.GetDescription()),
        }

        commits_table = self._version >= 1 and 'commits' or 'checkins'

        cursor = self.db.cursor()
        try:
            # MySQL-specific INSERT-or-UPDATE with ID retrieval
            cursor.execute(
                'INSERT INTO '+commits_table+'('+','.join(i for i in props)+') VALUES ('+
                ', '.join('%s' for i in props)+') ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), '+
                ', '.join(i+'=VALUES('+i+')' for i in props),
                tuple(props[i] for i in props)
            )
            commit_id = cursor.lastrowid
            if self.index_content:
                sphcur = self.sphinx.cursor()
                content = commit.GetContent()
                props['ci_when'] = str(int(commit.GetTime() or 0))
                if len(content):
                    # Maximum field size limit for Sphinx is 4MB
                    if len(content) > self.content_max_size:
                        content = content[0:self.content_max_size]
                    props['content'] = content
                    # Stored MIME type is only needed for snippet display
                    # It is re-guessed when the file is displayed
                    props['mimetype'] = commit.GetMimeType()
                    props['id'] = str(commit_id)
                    del props['addedlines']
                    del props['removedlines']
                    del props['descid']
                    del props['type']
                    sphcur.execute(
                        'INSERT INTO '+self.sphinx_index+'('+','.join(i for i in props)+') VALUES ('+
                        ','.join('%s' for i in props)+')',
                        tuple(props[i] for i in props)
                    )
                    # Sphinx (at least 2.0.1) still caches all string attributes
                    # inside RAM, so we'll store contents in MySQL
                    # Do not store contents of text files - it can be easily retrieved later
                    mime = props['mimetype']
                    if (self.enable_snippets and not (mime and
                        (mime.startswith('text/') or
                        mime.startswith('application/') and mime.endswith('xml')))):
                        cursor.execute('INSERT INTO contents SET id=%s, content=%s', (commit_id, content))
        except Exception, e:
            print ("Error adding commit: '"+str(e)+"'\nValues were:\n"+
                "\n".join(i+'='+str(props[i]) for i in props))
            raise

    def SQLQueryListString(self, field, query_entry_list):
        sqlList = []

        for query_entry in query_entry_list:
            data = query_entry.data
            ## figure out the correct match type
            if query_entry.match == "exact":
                match = "="
            elif query_entry.match == "like":
                match = " LIKE "
            elif query_entry.match == "glob":
                # check if the match is exact
                if not re.match(r'(\*|\?|\[.*\])', data):
                    match = "="
                else:
                    data = data.replace('%', '\\%')
                    data = data.replace('_', '\\_')
                    data = data.replace('*', '%')
                    data = data.replace('?', '_')
                    match = " LIKE "
            elif query_entry.match == "regex":
                match = " REGEXP "
            elif query_entry.match == "notregex":
                match = " NOT REGEXP "
            elif query_entry.match == "in":
                # now used only for repository type selection (viewvc.py/view_query)
                match = ''
                sqlList.append(field+' IN ('+string.join(map(lambda x: self.db.literal(x), data), ',')+')')
            if match != '':
                sqlList.append("%s%s%s" % (field, match, self.db.literal(data)))

        return "(%s)" % (string.join(sqlList, " OR "))

    def query_ids(self, in_field, table, id_field, name_field, lst):
        if not len(lst):
            return None
        cond = self.SQLQueryListString(name_field, lst)
        cursor = self.db.cursor()
        cursor.execute('SELECT %s FROM %s WHERE %s' % (id_field, table, cond))
        ids = list(str(row[0]) for row in cursor)
        if not len(ids):
            return None
        return "%s IN (%s)" % (in_field, ','.join(ids))

    def CreateSphinxQueryString(self, query):
        condList = [
            'MATCH(%s)' % (self.db.literal(query.content_query), ),
            self.query_ids('repositoryid', 'repositories', 'id', 'repository', query.repository_list),
            self.query_ids('branchid', 'branches', 'id', 'branch', query.branch_list),
            self.query_ids('dirid', 'dirs', 'id', 'dir', query.directory_list),
            self.query_ids('fileid', 'files', 'id', 'file', query.file_list),
            self.query_ids('authorid', 'people', 'id', 'who', query.author_list),
            self.query_ids('descid', 'descs', 'id', 'description', query.comment_list),
        ]

        if len(query.revision_list):
            condList.append("revision IN ("+','.join(self.db.literal(s) for s in query.revision_list)+")")
        if query.from_date:
            condList.append('ci_when>='+str(dbi.TicksFromDateTime(query.from_date)))
        if query.to_date:
            condList.append('ci_when<='+str(dbi.TicksFromDateTime(query.to_date)))

        if query.sort == 'date':
            order_by = 'ORDER BY `ci_when` DESC, `relevance` DESC'
        elif query.sort == 'date_rev':
            order_by = 'ORDER BY `ci_when` ASC, `relevance` DESC'
        else: # /* if query.sort == 'relevance' */
            order_by = 'ORDER BY `relevance` DESC, `ci_when` DESC'

        conditions = string.join((i for i in condList if i), " AND ")
        conditions = conditions and "WHERE %s" % conditions

        ## limit the number of rows requested or we could really slam
        ## a server with a large database
        limit = ""
        if query.limit:
            limit = "LIMIT %s" % (str(query.limit))
        elif self._row_limit:
            limit = "LIMIT %s" % (str(self._row_limit))

        fields = "id, `mimetype`, WEIGHT() `relevance`"

        return "SELECT %s FROM %s %s %s %s" % (fields, self.sphinx_index, conditions, order_by, limit)

    # Get commits by their IDs
    def CreateIdQueryString(self, ids):
        commits_table = self._version >= 1 and 'commits' or 'checkins'
        return (
            'SELECT %s.*, repositories.repository AS repository_name, dirs.dir AS dir_name, files.file AS file_name, "" AS snippet'
            ' FROM %s, repositories, dirs, files'
            ' WHERE %s.id IN (%s) AND repositoryid=repositories.id'
            ' AND dirid=dirs.id AND fileid=files.id' % (commits_table, commits_table, commits_table, ','.join(ids))
        )

    def CreateSQLQueryString(self, query):
        commits_table = self._version >= 1 and 'commits' or 'checkins'
        fields = [
            commits_table+".*",
            "repositories.repository AS repository_name",
            "dirs.dir AS dir_name",
            "files.file AS file_name"]
        tableList = [
            (commits_table, None),
            ("repositories", "(%s.repositoryid=repositories.id)" % (commits_table)),
            ("dirs", "(%s.dirid=dirs.id)" % (commits_table)),
            ("files", "(%s.fileid=files.id)" % (commits_table))]
        condList = []

        if len(query.text_query):
            tableList.append(("descs", "(descs.id=%s.descid)" % (commits_table)))
            temp = "MATCH (descs.description) AGAINST (%s" % (self.db.literal(query.text_query))
            condList.append("%s IN BOOLEAN MODE) > %s" % (temp, self._min_relevance))
            fields.append("%s) AS relevance" % temp)
        else:
            fields.append("'' AS relevance")
        fields.append("'' AS snippet")

        if len(query.repository_list):
            temp = self.SQLQueryListString("repositories.repository",
                                           query.repository_list)
            condList.append(temp)

        if len(query.branch_list):
            tableList.append(("branches", "(%s.branchid=branches.id)" % (commits_table)))
            temp = self.SQLQueryListString("branches.branch",
                                           query.branch_list)
            condList.append(temp)

        if len(query.directory_list):
            temp = self.SQLQueryListString("dirs.dir", query.directory_list)
            condList.append(temp)

        if len(query.file_list):
            tableList.append(("files", "(%s.fileid=files.id)" % (commits_table)))
            temp = self.SQLQueryListString("files.file", query.file_list)
            condList.append(temp)

        if len(query.revision_list):
            condList.append("(%s.revision IN (" % (commits_table) + ','.join(map(lambda s: self.db.literal(s), query.revision_list)) + "))")

        if len(query.author_list):
            tableList.append(("people", "(%s.whoid=people.id)" % (commits_table)))
            temp = self.SQLQueryListString("people.who", query.author_list)
            condList.append(temp)

        if len(query.comment_list):
            tableList.append(("descs", "(%s.descid=descs.id)" % (commits_table)))
            temp = self.SQLQueryListString("descs.description",
                                           query.comment_list)
            condList.append(temp)

        if query.from_date:
            temp = "(%s.ci_when>=\"%s\")" % (commits_table, str(query.from_date))
            condList.append(temp)

        if query.to_date:
            temp = "(%s.ci_when<=\"%s\")" % (commits_table, str(query.to_date))
            condList.append(temp)

        if query.sort == "relevance" and len(query.text_query):
            order_by = "ORDER BY relevance DESC,%s.ci_when DESC,descid,%s.repositoryid" % (commits_table, commits_table)
        elif query.sort == "date_rev":
            order_by = "ORDER BY %s.ci_when ASC,descid,%s.repositoryid" % (commits_table, commits_table)
        elif query.sort == "author":
            tableList.append(("people", "(%s.whoid=people.id)" % (commits_table)))
            order_by = "ORDER BY people.who,descid,%s.repositoryid" % (commits_table)
        elif query.sort == "file":
            tableList.append(("files", "(%s.fileid=files.id)" % (commits_table)))
            order_by = "ORDER BY files.file,descid,%s.repositoryid" % (commits_table)
        else: # /* if query.sort == "date": */
            order_by = "ORDER BY %s.ci_when DESC,descid,%s.repositoryid" % (commits_table, commits_table)

        ## exclude duplicates from the table list, and split out join
        ## conditions from table names.  In future, the join conditions
        ## might be handled by INNER JOIN statements instead of WHERE
        ## clauses, but MySQL 3.22 apparently doesn't support them well.
        tables = []
        joinConds = []
        for (table, cond) in tableList:
            if table not in tables:
                tables.append(table)
                if cond is not None: joinConds.append(cond)

        fields = string.join(fields, ",")
        tables = string.join(tables, ",")
        conditions = string.join(joinConds + condList, " AND ")
        conditions = conditions and "WHERE %s" % conditions

        ## limit the number of rows requested or we could really slam
        ## a server with a large database
        limit = ""
        if query.limit:
            limit = "LIMIT %s" % (str(query.limit))
        elif self._row_limit:
            limit = "LIMIT %s" % (str(self._row_limit))

        sql = "SELECT %s FROM %s %s %s %s" % (
            fields, tables, conditions, order_by, limit)

        return sql

    # Check access to dir/file in repository repos
    def check_commit_access(self, repos, dir, file, rev):
        r = self.request.get_repo(repos)
        if not r:
            return False
        if r.auth:
            rootname = repos.split('/')
            rootname = rootname.pop()
            path_parts = dir.split('/')
            path_parts.append(file)
            return r.auth.check_path_access(rootname, path_parts, vclib.FILE, rev)
        return True

    # Build a snippet using Sphinx
    def get_snippet(self, sph, content, query, mimetype):
        sph.execute(
            'CALL SNIPPETS(%s, %s, %s'+self.snippet_options_str+')',
            (content, self.sphinx_index, query) + tuple(self.snippet_options.values())
        )
        s, = sph.fetchone()
        s = cgi.escape(s)
        if re.match(self.preformatted_mime, mimetype):
            s = s.replace('\n', '<br />')
        if 'before_match' in self.snippet_options:
            s = s.replace(self.snippet_beforematch_html, self.snippet_options['before_match'])
        if 'after_match' in self.snippet_options:
            s = s.replace(self.snippet_aftermatch_html, self.snippet_options['after_match'])
        return s

    # Fetch snippets for a query result
    def fetch_snippets(self, query, rows):
        if not len(rows):
            return
        cursor = self.db.cursor()
        sph = self.sphinx.cursor()
        # Fetch binary file contents, stored in MySQL
        cursor.execute(
            'SELECT id, content FROM contents WHERE id IN (' +
            ','.join(rows.keys()) + ')'
        )
        # Build snippets
        for (docid, content) in cursor:
            rows[str(docid)]['snippet'] = self.get_snippet(sph, content, query.content_query, rows[str(docid)]['mimetype'])
        for docid in rows:
            mime = rows[docid]['mimetype']
            if (not rows[docid]['snippet'] and mime and
               (mime.startswith('text/') or (mime.startswith('application/') and mime.endswith('xml')))):
                # Fetch text file contents directly from SVN
                repo = rows[docid]['repository_name']
                path = rows[docid]['dir_name'].split('/') + [rows[docid]['file_name']]
                revision = rows[docid]['revision']
                fp = None
                try:
                    fp, _ = self.request.get_repo(repo).repos.openfile(path, revision)
                    content = fp.read()
                    fp.close()
                    content = self.guesser.utf8(content)
                except:
                    if fp: fp.close()
                    content = None
                    raise
                # Build snippet
                if content:
                    rows[docid]['snippet'] = self.get_snippet(sph, content, query.content_query, rows[docid]['mimetype'])

    # Run query and return all rows as dictionaries
    def selectall(self, db, sql, args = None, key = None):
        cursor = db.cursor()
        cursor.execute(sql, args)
        desc = list(r[0] for r in cursor.description)
        if key:
            rows = {}
            for i in cursor:
                r = dict(zip(desc, i))
                rows[str(r[key])] = r
        else:
            rows = []
            for i in cursor:
                rows.append(dict(zip(desc, i)))
        return rows

    # Run content query
    def RunSphinxQuery(self, query):
        cursor = self.db.cursor()
        rows = self.selectall(self.sphinx, self.CreateSphinxQueryString(query))
        if len(rows):
            for r in rows:
                r['id'] = str(r['id'])
            m_rows = self.selectall(self.db, self.CreateIdQueryString((r['id'] for r in rows)), None, 'id')
            new_rows = []
            # Check rights BEFORE fetching snippets
            for i in rows:
                if i['id'] in m_rows:
                    if not self.check_commit_access(
                        m_rows[i['id']]['repository_name'],
                        m_rows[i['id']]['dir_name'],
                        m_rows[i['id']]['file_name'],
                        m_rows[i['id']]['revision']):
                        del m_rows[i['id']]
                    else:
                        m_rows[i['id']].update(i)
            # Fetch snippets
            if self.enable_snippets:
                self.fetch_snippets(query, m_rows)
            for i in rows:
                if i['id'] in m_rows:
                    new_rows.append(m_rows[i['id']])
            rows = new_rows
        else:
            rows = []
        return rows

    def RunQuery(self, query):
        if len(query.content_query) and self.sphinx:
            # Use Sphinx to search on document content
            rows = self.RunSphinxQuery(query)
        else:
            # Use regular queries when document content is not searched
            rows = self.selectall(self.db, self.CreateSQLQueryString(query))
            # Check rights
            rows = (r for r in rows if self.check_commit_access(
                r['repository_name'],
                r['dir_name'],
                r['file_name'],
                r['revision']))

        # Convert rows to commit objects
        for row in rows:
            commit = LazyCommit(self)
            if row['type'] == 'Add':
                commit.SetTypeAdd()
            elif row['type'] == 'Remove':
                commit.SetTypeRemove()
            else:
                commit.SetTypeChange()

            commit.SetTime(dbi.TicksFromDateTime(row['ci_when']))
            commit.SetFileID(row['fileid'])
            commit.SetDirectoryID(row['dirid'])
            commit.SetRevision(row['revision'])
            commit.SetRepositoryID(row['repositoryid'])
            commit.SetAuthorID(row['whoid'])
            commit.SetBranchID(row['branchid'])
            commit.SetPlusCount(row['addedlines'])
            commit.SetMinusCount(row['removedlines'])
            commit.SetDescriptionID(row['descid'])
            commit.SetRelevance(row['relevance'])
            commit.SetSnippet(row['snippet'])

            query.AddCommit(commit)

    def CheckCommit(self, commit):
        repository_id = self.GetRepositoryID(commit.GetRepository(), 0)
        if repository_id == None:
            return None

        dir_id = self.GetDirectoryID(commit.GetDirectory(), 0)
        if dir_id == None:
            return None

        file_id = self.GetFileID(commit.GetFile(), 0)
        if file_id == None:
            return None

        commits_table = self._version >= 1 and 'commits' or 'checkins'
        sql = "SELECT whoid FROM %s WHERE "\
              "  repositoryid=%%s "\
              "  AND dirid=%%s"\
              "  AND fileid=%%s"\
              "  AND revision=%%s"\
              % (commits_table)
        sql_args = (repository_id, dir_id, file_id, commit.GetRevision())

        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)
        try:
            who_id, = cursor.fetchone()
        except TypeError:
            return None

        return commit

    # Now unused
    def sql_delete(self, table, key, value, keep_fkey = None):
        sql = "DELETE FROM %s WHERE %s=%%s" % (table, key)
        sql_args = (value, )
        commits_table = self._version >= 1 and 'commits' or 'checkins'
        if keep_fkey:
            sql += " AND %s NOT IN (SELECT %s FROM %s WHERE %s = %%s)" \
                   % (key, keep_fkey, commits_table, keep_fkey)
            sql_args = (value, value)
        cursor = self.db.cursor()
        cursor.execute(sql, sql_args)

    def sql_purge(self, table, key, fkey, ftable):
        sql = "DELETE FROM %s WHERE %s NOT IN (SELECT %s FROM %s)" \
              % (table, key, fkey, ftable)
        cursor = self.db.cursor()
        cursor.execute(sql)

    # Purge a repository fully or partially
    def PurgeRepository(self, repository, path_prefix = None):
        rep_id = self.GetRepositoryID(repository, auto_set=0)
        if not rep_id:
            raise UnknownRepositoryError("Unknown repository '%s'"
                                         % (repository))

        checkins_table = self._version >= 1 and 'commits' or 'checkins'

        # Purge checkins
        cursor = self.db.cursor()
        tables = "DELETE FROM c USING %s c" % (checkins_table, )
        where = " WHERE c.repositoryid=%s"
        args = (rep_id, )
        if path_prefix is not None:
            tables = tables + ", dirs d"
            where = where + " AND d.id=c.dirid AND (d.dir=%s OR d.dir LIKE %s)"
            args = args + (path_prefix, path_prefix+'/%')
        cursor.execute(tables+where, args)

        # Purge unreferenced items
        self.sql_purge('repositories', 'id', 'repositoryid', checkins_table)
        self.sql_purge('files', 'id', 'fileid', checkins_table)
        self.sql_purge('dirs', 'id', 'dirid', checkins_table)
        self.sql_purge('branches', 'id', 'branchid', checkins_table)
        self.sql_purge('descs', 'id', 'descid', checkins_table)
        self.sql_purge('people', 'id', 'whoid', checkins_table)
        self.sql_purge('contents', 'id', 'id', checkins_table)

        # Reset all internal id caches.  We could be choosier here,
        # but let's just be as safe as possible.
        self._get_cache = {}
        self._get_id_cache = {}
        self._desc_id_cache = {}


class DatabaseVersionError(Exception):
    pass
class UnknownRepositoryError(Exception):
    pass


## the Commit class holds data on one commit, the representation is as
## close as possible to how it should be committed and retrieved to the
## database engine
class Commit:
    ## static constants for type of commit
    CHANGE = 0
    ADD = 1
    REMOVE = 2

    def __init__(self):
        self.__directory = ''
        self.__file = ''
        self.__repository = ''
        self.__revision = ''
        self.__author = ''
        self.__branch = ''
        self.__pluscount = ''
        self.__minuscount = ''
        self.__description = ''
        self.__relevance = ''
        self.__snippet = ''
        self.__gmt_time = 0.0
        self.__type = Commit.CHANGE
        self.__content = ''
        self.__mimetype = ''
        self.__base_path = ''
        self.__base_rev = ''

    def SetRepository(self, repository):
        self.__repository = repository

    def GetRepository(self):
        return self.__repository

    def SetDirectory(self, dir):
        self.__directory = dir

    def GetDirectory(self):
        return self.__directory

    def SetFile(self, file):
        self.__file = file

    def GetFile(self):
        return self.__file

    def SetRevision(self, revision):
        self.__revision = revision

    def GetRevision(self):
        return self.__revision

    def SetTime(self, gmt_time):
        if gmt_time is None:
            ### We're just going to assume that a datestamp of The Epoch
            ### ain't real.
            self.__gmt_time = 0.0
        else:
            self.__gmt_time = float(gmt_time)

    def GetTime(self):
        return self.__gmt_time and self.__gmt_time or None

    def SetAuthor(self, author):
        self.__author = author

    def GetAuthor(self):
        return self.__author

    def SetBranch(self, branch):
        self.__branch = branch or ''

    def GetBranch(self):
        return self.__branch

    def SetPlusCount(self, pluscount):
        self.__pluscount = pluscount

    def GetPlusCount(self):
        return self.__pluscount

    def SetMinusCount(self, minuscount):
        self.__minuscount = minuscount

    def GetMinusCount(self):
        return self.__minuscount

    def SetDescription(self, description):
        self.__description = description

    def GetDescription(self):
        return self.__description

    # Relevance and snippet are used when querying commit database
    def SetRelevance(self, relevance):
        self.__relevance = relevance

    def GetRelevance(self):
        return self.__relevance

    def SetSnippet(self, snippet):
        self.__snippet = snippet

    def GetSnippet(self):
        return self.__snippet

    def SetTypeChange(self):
        self.__type = Commit.CHANGE

    def SetTypeAdd(self):
        self.__type = Commit.ADD

    def SetTypeRemove(self):
        self.__type = Commit.REMOVE

    def GetType(self):
        return self.__type

    def GetTypeString(self):
        if self.__type == Commit.CHANGE:
            return 'Change'
        elif self.__type == Commit.ADD:
            return 'Add'
        elif self.__type == Commit.REMOVE:
            return 'Remove'

    # File content (extracted text), optional, indexed with Sphinx
    def SetContent(self, content):
        self.__content = content

    def GetContent(self):
        return self.__content

    # MIME type, optional, now only stored in Sphinx
    def SetMimeType(self, mimetype):
        self.__mimetype = mimetype

    def GetMimeType(self):
        return self.__mimetype

## LazyCommit overrides a few methods of Commit to only retrieve
## it's properties as they are needed
class LazyCommit(Commit):
    def __init__(self, db):
        Commit.__init__(self)
        self.__db = db

    def SetFileID(self, dbFileID):
        self.__dbFileID = dbFileID

    def GetFileID(self):
        return self.__dbFileID

    def GetFile(self):
        return self.__db.GetFile(self.__dbFileID)

    def SetDirectoryID(self, dbDirID):
        self.__dbDirID = dbDirID

    def GetDirectoryID(self):
        return self.__dbDirID

    def GetDirectory(self):
        return self.__db.GetDirectory(self.__dbDirID)

    def SetRepositoryID(self, dbRepositoryID):
        self.__dbRepositoryID = dbRepositoryID

    def GetRepositoryID(self):
        return self.__dbRepositoryID

    def GetRepository(self):
        return self.__db.GetRepository(self.__dbRepositoryID)

    def SetAuthorID(self, dbAuthorID):
        self.__dbAuthorID = dbAuthorID

    def GetAuthorID(self):
        return self.__dbAuthorID

    def GetAuthor(self):
        return self.__db.GetAuthor(self.__dbAuthorID)

    def SetBranchID(self, dbBranchID):
        self.__dbBranchID = dbBranchID

    def GetBranchID(self):
        return self.__dbBranchID

    def GetBranch(self):
        return self.__db.GetBranch(self.__dbBranchID)

    def SetDescriptionID(self, dbDescID):
        self.__dbDescID = dbDescID

    def GetDescriptionID(self):
        return self.__dbDescID

    def GetDescription(self):
        return self.__db.GetDescription(self.__dbDescID)

## QueryEntry holds data on one match-type in the SQL database
## match is: "exact", "like", or "regex"
class QueryEntry:
    def __init__(self, data, match):
        self.data = data
        self.match = match

## CheckinDatabaseQueryData is a object which contains the search parameters
## for a query to the CheckinDatabase
class CheckinDatabaseQuery:
    def __init__(self):
        ## sorting
        self.sort = "date"

        ## repository, branch, etc to query
        self.repository_list = []
        self.branch_list = []
        self.directory_list = []
        self.file_list = []
        self.revision_list = []
        self.author_list = []
        self.comment_list = []

        ## text_query = Fulltext query on comments
        ## content_query = Fulltext query on content
        self.text_query = ""
        self.content_query = ""

        ## date range in DBI 2.0 timedate objects
        self.from_date = None
        self.to_date = None

        ## limit on number of rows to return
        self.limit = None

        ## list of commits -- filled in by CVS query
        self.commit_list = []

        ## commit_cb provides a callback for commits as they
        ## are added
        self.commit_cb = None

    def SetTextQuery(self, query):
        self.text_query = query

    def SetContentQuery(self, query):
        self.content_query = query

    def SetRepository(self, repository, match = "exact"):
        if match == 'exact' and repository.find('/') == -1:
            # Exact match on the last part of repository name
            match = 'like'
            repository = '%/' + repository.replace('%', '\\%')
        self.repository_list.append(QueryEntry(repository, match))

    def SetBranch(self, branch, match = "exact"):
        self.branch_list.append(QueryEntry(branch, match))

    def SetDirectory(self, directory, match = "exact"):
        self.directory_list.append(QueryEntry(directory, match))

    def SetFile(self, file, match = "exact"):
        self.file_list.append(QueryEntry(file, match))

    def SetRevision(self, revision):
        r = re.compile('\s*[,;]+\s*')
        for i in r.split(revision):
            self.revision_list.append(i)

    def SetAuthor(self, author, match = "exact"):
        self.author_list.append(QueryEntry(author, match))

    def SetComment(self, comment, match = "fulltext"):
        self.comment_list.append(QueryEntry(comment, match))

    def SetSortMethod(self, sort):
        self.sort = sort

    def SetFromDateObject(self, ticks):
        self.from_date = dbi.DateTimeFromTicks(ticks)

    def SetToDateObject(self, ticks):
        self.to_date = dbi.DateTimeFromTicks(ticks)

    def SetFromDateHoursAgo(self, hours_ago):
        ticks = time.time() - (3600 * hours_ago)
        self.from_date = dbi.DateTimeFromTicks(ticks)

    def SetFromDateDaysAgo(self, days_ago):
        ticks = time.time() - (86400 * days_ago)
        self.from_date = dbi.DateTimeFromTicks(ticks)

    def SetToDateDaysAgo(self, days_ago):
        ticks = time.time() - (86400 * days_ago)
        self.to_date = dbi.DateTimeFromTicks(ticks)

    def SetLimit(self, limit):
        self.limit = limit;

    def AddCommit(self, commit):
        self.commit_list.append(commit)


##
## entrypoints
##
def CreateCommit():
    return Commit()

def CreateCheckinQuery():
    return CheckinDatabaseQuery()

def ConnectDatabase(cfg, request=None, readonly=0):
    db = CheckinDatabase(
        readonly = readonly,
        request = request,
        cfg = cfg.cvsdb,
        guesser = cfg.guesser(),
    )
    db.Connect()
    return db

def ConnectDatabaseReadOnly(cfg, request):
    return ConnectDatabase(cfg, request, 1)

# Get all commits from rcsfile (CVS)
def GetCommitListFromRCSFile(repository, path_parts, revision=None):
    commit_list = []

    directory = string.join(path_parts[:-1], "/")
    file = path_parts[-1]

    revs = repository.itemlog(path_parts, revision, vclib.SORTBY_DEFAULT,
                              0, 0, {"cvs_pass_rev": 1})
    for rev in revs:
        commit = CreateCommit()
        commit.SetRepository(repository.rootpath)
        commit.SetDirectory(directory)
        commit.SetFile(file)
        commit.SetRevision(rev.string)
        commit.SetAuthor(rev.author)
        commit.SetDescription(rev.log)
        commit.SetTime(rev.date)

        if rev.changed:
            # extract the plus/minus and drop the sign
            plus, minus = string.split(rev.changed)
            commit.SetPlusCount(plus[1:])
            commit.SetMinusCount(minus[1:])

            if rev.dead:
                commit.SetTypeRemove()
            else:
                commit.SetTypeChange()
        else:
            commit.SetTypeAdd()

        commit_list.append(commit)

        # if revision is on a branch which has at least one tag
        if len(rev.number) > 2 and rev.branches:
            commit.SetBranch(rev.branches[0].name)

    return commit_list

# Get unrecorded commits from rcsfile (CVS)
def GetUnrecordedCommitList(repository, path_parts, db):
    commit_list = GetCommitListFromRCSFile(repository, path_parts)

    unrecorded_commit_list = []
    for commit in commit_list:
        result = db.CheckCommit(commit)
        if not result:
            unrecorded_commit_list.append(commit)

    return unrecorded_commit_list

_re_likechars = re.compile(r"([_%\\])")

def EscapeLike(literal):
  """Escape literal string for use in a MySQL LIKE pattern"""
  return re.sub(_re_likechars, r"\\\1", literal)

def FindRepository(db, path):
  """Find repository path in database given path to subdirectory
  Returns normalized repository path and relative directory path"""
  path = os.path.normpath(path)
  dirs = []
  while path:
    rep = os.path.normcase(path)
    if db.GetRepositoryID(rep, 0) is None:
      path, pdir = os.path.split(path)
      if not pdir:
        return None, None
      dirs.append(pdir)
    else:
      break
  dirs.reverse()
  return rep, dirs

def CleanRepository(path):
  """Return normalized top-level repository path"""
  return os.path.normcase(os.path.normpath(path))

