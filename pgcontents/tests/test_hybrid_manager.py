# coding: utf-8
"""
Tests for HybridContentsManager.
"""
from os import (
    makedirs,
    mkdir,
)
from os.path import (
    exists,
    join as osjoin,
)
from posixpath import join as pjoin

from six import (
    iteritems,
    itervalues,
)
from unittest import TestCase
from unittest.mock import Mock

from IPython.utils.tempdir import TemporaryDirectory

from pgcontents.hybridmanager import HybridContentsManager

from .utils import assertRaisesHTTPError

from ..utils.ipycompat import APITest, FileContentsManager, TestContentsManager

TEST_FILE_NAME = "Untitled.ipynb"


def _make_dir(contents_manager, api_path):
    """
    Make a directory.
    """
    os_path = contents_manager._get_os_path(api_path)
    try:
        makedirs(os_path)
    except OSError:
        print("Directory already exists: %r" % os_path)


class FileTestCase(TestContentsManager):
    def setUp(self):
        self._temp_dir = TemporaryDirectory()
        self.td = self._temp_dir.name
        self._file_manager = FileContentsManager(root_dir=self.td,
                                                 delete_to_trash=False)
        self.contents_manager = HybridContentsManager(
            managers={'': self._file_manager})

    def tearDown(self):
        self._temp_dir.cleanup()

    def make_dir(self, api_path):
        """make a subdirectory at api_path
        override in subclasses if contents are not on the filesystem.
        """
        _make_dir(self._file_manager, api_path)


class MultiRootTestCase(TestCase):
    def setUp(self):

        mgr_roots = ['A', '', u'unicodé']
        self.temp_dirs = {prefix: TemporaryDirectory() for prefix in mgr_roots}
        self.temp_dir_names = {
            prefix: v.name
            for prefix, v in iteritems(self.temp_dirs)
        }
        self._managers = {
            prefix: FileContentsManager(root_dir=self.temp_dir_names[prefix],
                                        delete_to_trash=False)
            for prefix in mgr_roots
        }
        self.contents_manager = HybridContentsManager(managers=self._managers)

    def test_get(self):
        cm = self.contents_manager

        untitled_txt = 'untitled.txt'
        for prefix, real_dir in iteritems(self.temp_dir_names):
            # Create a notebook
            model = cm.new_untitled(path=prefix, type='notebook')
            name = model['name']
            path = model['path']

            self.assertEqual(name, TEST_FILE_NAME)
            self.assertEqual(path, pjoin(prefix, TEST_FILE_NAME))
            self.assertTrue(exists(osjoin(real_dir, TEST_FILE_NAME)))

            # Check that we can 'get' on the notebook we just created
            model2 = cm.get(path)
            assert isinstance(model2, dict)
            self.assertDictContainsSubset(
                {
                    'name': name,
                    'path': path
                },
                model2,
            )

            nb_as_file = cm.get(path, content=True, type='file')
            self.assertDictContainsSubset(
                {
                    'name': name,
                    'path': path,
                    'format': 'text'
                },
                nb_as_file,
            )
            self.assertNotIsInstance(nb_as_file['content'], dict)

            nb_as_bin_file = cm.get(path=path,
                                    content=True,
                                    type='file',
                                    format='base64')
            self.assertDictContainsSubset(
                {
                    'name': name,
                    'path': path,
                    'format': 'base64'
                },
                nb_as_bin_file,
            )
            self.assertNotIsInstance(nb_as_bin_file['content'], dict)

            # Test notebook in sub-directory
            sub_dir = 'foo'
            mkdir(osjoin(real_dir, sub_dir))
            prefixed_sub_dir = pjoin(prefix, sub_dir)

            cm.new_untitled(path=prefixed_sub_dir, ext='.ipynb')
            self.assertTrue(exists(osjoin(real_dir, sub_dir, TEST_FILE_NAME)))

            sub_dir_nbpath = pjoin(prefixed_sub_dir, TEST_FILE_NAME)
            model2 = cm.get(sub_dir_nbpath)
            self.assertDictContainsSubset(
                {
                    'type': 'notebook',
                    'format': 'json',
                    'name': TEST_FILE_NAME,
                    'path': sub_dir_nbpath,
                },
                model2,
            )
            self.assertIn('content', model2)

            # Test .txt in sub-directory.
            cm.new_untitled(path=prefixed_sub_dir, ext='.txt')
            self.assertTrue(exists(osjoin(real_dir, sub_dir, untitled_txt)))

            sub_dir_txtpath = pjoin(prefixed_sub_dir, untitled_txt)
            file_model = cm.get(path=sub_dir_txtpath)
            self.assertDictContainsSubset(
                {
                    'content': '',
                    'format': 'text',
                    'mimetype': 'text/plain',
                    'name': 'untitled.txt',
                    'path': sub_dir_txtpath,
                    'type': 'file',
                    'writable': True,
                },
                file_model,
            )
            self.assertIn('created', file_model)
            self.assertIn('last_modified', file_model)

            # Test directory in sub-directory.
            sub_sub_dirname = 'bar'
            sub_sub_dirpath = pjoin(prefixed_sub_dir, sub_sub_dirname)
            cm.save(
                {
                    'type': 'directory',
                    'path': sub_sub_dirpath
                },
                sub_sub_dirpath,
            )
            self.assertTrue(exists(osjoin(real_dir, sub_dir, sub_sub_dirname)))
            sub_sub_dir_model = cm.get(sub_sub_dirpath)
            self.assertDictContainsSubset(
                {
                    'type': 'directory',
                    'format': 'json',
                    'name': sub_sub_dirname,
                    'path': sub_sub_dirpath,
                    'content': [],
                },
                sub_sub_dir_model,
            )

            # Test list with content on prefix/foo.
            dirmodel = cm.get(prefixed_sub_dir)
            self.assertDictContainsSubset(
                {
                    'type': 'directory',
                    'path': prefixed_sub_dir,
                    'name': sub_dir,
                },
                dirmodel,
            )
            self.assertIsInstance(dirmodel['content'], list)
            self.assertEqual(len(dirmodel['content']), 3)

            # Request each item in the subdirectory with no content.
            nbmodel_no_content = cm.get(sub_dir_nbpath, content=False)
            file_model_no_content = cm.get(sub_dir_txtpath, content=False)
            sub_sub_dir_no_content = cm.get(sub_sub_dirpath, content=False)

            for entry in dirmodel['content']:
                # Order isn't guaranteed by the spec, so this is a hacky way of
                # verifying that all entries are matched.
                if entry['path'] == sub_sub_dir_no_content['path']:
                    self.assertEqual(entry, sub_sub_dir_no_content)
                elif entry['path'] == nbmodel_no_content['path']:
                    self.assertEqual(entry, nbmodel_no_content)
                elif entry['path'] == file_model_no_content['path']:
                    self.assertEqual(entry, file_model_no_content)
                else:
                    self.fail("Unexpected directory entry: %s" % entry)

    def test_root_dir_ops(self):
        cm = self.contents_manager
        cm.new_untitled(ext='.ipynb')
        cm.new_untitled(ext='.txt')

        root_dir_model = cm.get('')
        self.assertDictContainsSubset(
            {
                'path': '',
                'name': '',
                'type': 'directory',
                'format': 'json'
            },
            root_dir_model,
        )
        content = root_dir_model['content']
        self.assertIsInstance(content, list)
        # Two new files, plus the sub-manager directories.
        dirs = set(self.temp_dir_names)
        files = {TEST_FILE_NAME, 'untitled.txt'}
        paths = dirs | files
        self.assertEqual(len(content), 4)
        for entry in content:
            self.assertEqual(entry['path'], entry['name'])
            path = entry['path']
            if path not in paths:
                self.fail("Unexpected entry path %s" % entry)
            if path in dirs:
                self.assertEqual(entry['type'], 'directory')
            elif path == TEST_FILE_NAME:
                self.assertEqual(entry['type'], 'notebook')
            else:
                self.assertEqual(entry['type'], 'file')

    def test_cant_delete_root(self):
        cm = self.contents_manager
        for prefix in self.temp_dirs:
            with assertRaisesHTTPError(self, 400):
                cm.delete(prefix)

    def test_cant_rename_root(self):
        cm = self.contents_manager

        with assertRaisesHTTPError(self, 400):
            cm.rename('', 'A')

    def test_rename_submanager_calls(self):
        cm = self.contents_manager
        cm.new_untitled(ext='.ipynb')

        new_path = 'A/test/Untitled.ipynb'

        old_manager = self._managers['']
        new_manager = self._managers['A']

        # Configure Mocks
        old_manager.delete = Mock()
        new_manager.save = Mock()
        old_manager.get = Mock()

        # Get test data
        old_model = old_manager.get(TEST_FILE_NAME)
        new_relative_path = 'test/Untitled.ipynb'

        # Make calls
        cm.rename(TEST_FILE_NAME, new_path)

        # Run tests
        old_manager.delete.assert_called_with(TEST_FILE_NAME)
        old_manager.get.assert_called_with(TEST_FILE_NAME)
        new_manager.save.assert_called_with(old_model, new_relative_path)

    def test_can_rename_across_managers(self):
        cm = self.contents_manager
        cm.new_untitled(ext='.ipynb')

        new_path = 'A/Untitled.ipynb'

        cm.rename(TEST_FILE_NAME, new_path)

        with assertRaisesHTTPError(self, 404):
            cm.get(TEST_FILE_NAME)

        model2 = cm.get(new_path)

        self.assertIn('path', model2)

    def tearDown(self):
        for dir_ in itervalues(self.temp_dirs):
            dir_.cleanup()


del TestContentsManager
del APITest
