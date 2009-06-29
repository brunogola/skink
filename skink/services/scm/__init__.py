#!/usr/bin/env python
# -*- coding:utf-8 -*-

import sys
from os.path import dirname, abspath, join, exists
import os
root_path = abspath(join(dirname(__file__), "../../"))
sys.path.insert(0, root_path)

import re
import shutil
from datetime import datetime
import time

from skink.context import SkinkContext
from skink.services.executers import ShellExecuter


class ScmRepository(object):
    name = NotImplemented
    update_cmd = NotImplemented
    retrieve_cmd = NotImplemented

    def __init__(self, base_dir):
        self.base_dir = base_dir

    def get_last_commit(self, repository_path):
        return NotImplemented

    def execute_verification_command(self, executer, repository_path):
        return NotImplemented

    @classmethod
    def get_scm(cls, project):
        return [ scm for scm in cls.get_available_scms() if scm.name == project.scm ][0]

    @classmethod
    def get_available_scms(cls):
        return cls.__subclasses__()

    def log(self, message):
        ctx = SkinkContext.current()
        if ctx.scm_verbose:
            print message

    def fix_name(self, name):
        return name.strip().replace(" ", "")

    def create_or_update(self, project):
        executer = ShellExecuter()
        project_name = self.fix_name(project.name)
        repository_path = join(self.base_dir, project_name)
        is_repo_created = self.is_repository_created(repository_path)
        if not is_repo_created and exists(repository_path):
            raise ValueError("The specified directory(%s) is not empty and is not a repository")
        if not is_repo_created:
            if not exists(self.base_dir):
                try:
                    os.mkdir(self.base_dir)
                except:
                    raise ValueError("Could not create folder %s" % self.base_dir)
                self.log("Directory successfully created.")

            self.log("Retrieving scm data for project %s in repository %s (creating new repository)" % (project_name, project.scm_repository))
            import pdb;pdb.set_trace()
            result = executer.execute("%s \"%s\" \"%s\"" % (self.retrieve_cmd, project.scm_repository, project_name), self.base_dir)
            if result.exit_code == 0:
                self.log("SCM Data retrieved successfully")
            else:
                self.log("Error retrieving SCM Data: %s" % result.run_log)
            last_commit = self.get_last_commit(repository_path)
            return ScmResult(result.exit_code == 0 and ScmResult.Created or ScmResult.Failed, repository_path, last_commit, result.run_log)
        else:
            self.log("Retrieving scm data for project %s in repository %s (updating repository)" % (project_name, project.scm_repository))
            result = executer.execute(self.update_cmd, repository_path)
            if result.exit_code == 0:
                self.log("SCM Data retrieved successfully")
            else:
                self.log("Error retrieving SCM Data: %s" % result.run_log)
            
            self.log("Retrieving last commit data for project %s in repository %s" % (project_name, project.scm_repository))

    def remove_repository(self, project):
        project_name = self.fix_name(project.name)
        repository_path = join(self.base_dir, project_name)
        is_repo_created = self.is_repository_created(repository_path)
        if not is_repo_created:
            return None
        
        shutil.rmtree(repository_path)

    def is_repository_created(self, path):
        if not exists(path) or not exists(join(path, ".%s" % self.scm)):
            return False
        return True
    
    def does_project_need_update(self, project):
        executer = ShellExecuter()
        project_name = self.fix_name(project.name)
        repository_path = join(self.base_dir, project_name)
        is_repo_created = self.is_repository_created(repository_path)
        
        if not is_repo_created:
            self.log("The repository at %s needs to be created." % repository_path)
            return True
        
        self.log("Verifying if the repository at %s needs to be updated" % repository_path)
        
        scm = [ scmClass for scmClass in self.__subclasses__() if scmClass.scm == project.scm ][0]
        return scm.execute_verification_command(executer, repository_path)

    def convert_to_date(self, dt):
        dt = " ".join(dt.split(" ")[:2])
        time_components = time.strptime(dt.strip(), "%Y-%m-%d %H:%M:%S")[:6]
        now = datetime(*time_components)
        return now


class ScmResult(object):
    Created = u"CREATED"
    Updated = u"UPDATED"
    Failed = u"FAILED"
    
    def __init__(self, status, repository_path, last_commit, log):
        self.status = status
        self.repository_path = repository_path
        self.last_commit = last_commit
        self.log = log


# Specific SCMs

class SvnRepository(ScmRepository):
    name = "svn"
    update_cmd = "svn up"
    retrieve_cmd = "svn checkout"

    def execute_verification_command(self, executer, repository_path):
        result = executer.execute("svn -u st | grep -v '^?'", repository_path)
        commits = result.run_log
        return len(commits.split("\n")) > 1

    def _execute_svn_log(self, repository_path, rev=False):
        executer = ShellExecuter()
        
        command = "svn log -l 1 --xml"
        if rev is not False:
            command = "svn -r %d log -l 1 --xml" % rev

        result = executer.execute(command, repository_path)
        
        if result.exit_code != 0:
            raise ValueError("unable to determine commit. Error: %s" % result.run_log)
        return result

    def get_last_commit(self, repository_path):
        result = self._execute_svn_log(repository_path, rev=1)
        first_svn_commit = self._parse_svn_log(result)

        result = self._execute_svn_log(repository_path)
        parsed_result = self._parse_svn_log(result)

        parsed_result['author'] = first_svn_commit['author']
        parsed_result['author_date'] = first_svn_commit['author_date']
        return parsed_result

    def _parse_svn_log(self, result):
        author = re.search(r'<author>([A-Za-z]+)</author>', result.run_log).groups()[0]
        commit_number = re.search(r'revision="([0-9]+)">', result.run_log).groups()[0]
        subject = re.search(r'<msg>([^<>/]+)</msg>', result.run_log).groups()[0]
        date = re.search(r'<date>(\d+-\d+-\d+T\d+:\d+:\d+)\.[A-Za-z0-9]+</date>', result.run_log).groups()[0]
        date = time.strptime(date.strip(), "%Y-%m-%dT%H:%M:%S")[:6]
        date = datetime(*date)

        return {
                   'commit_number': commit_number,
                   'author': "%s" % author,
                   'author_date': date,
                   'committer': "%s" % author,
                   'committer_date': date,
                   'subject': subject
               }


class GitRepository(ScmRepository):
    name = "git"
    update_cmd = "git pull"
    retrieve_cmd = "git clone"
    
    def execute_verification_command(self, executer, repository_path):
        executer.execute("git remote update", repository_path)
        result = executer.execute("git rev-parse origin master", repository_path)
        commits = result.run_log.split()
        return len(commits) != 2 or commits[0]!=commits[1]

    def get_last_commit(self, repository_path):
        commit_number = None
        author = None
        committer = None

        command = "git show -s --pretty=format:'%H||%an||%ae||%ai||%cn||%ce||%ci||%s'"
        
        executer = ShellExecuter()
        result = executer.execute(command, repository_path)
        
        if result.exit_code != 0:
            raise ValueError("unable to determine last commit. Error: %s" % result.run_log)
        commit_number, author_name, author_email, author_date, committer_name, committer_email, committer_date, subject = result.run_log.split("||")
        
        author_date = self.convert_to_date(author_date)
        committer_date = self.convert_to_date(committer_date)
        
        return {
                   'commit_number': commit_number,
                   'author': "%s <%s>" % (author_name, author_email),
                   'author_date': author_date,
                   'committer': "%s <%s>" % (committer_name, committer_email),
                   'committer_date': committer_date,
                   'subject': subject
               }
