#!/usr/bin/env bash

set -ex

if [[ "$(uname -s)" == 'Darwin' ]]; then
    brew update || brew update
    brew outdated pyenv || brew upgrade pyenv
    brew install pyenv-virtualenv
    brew install cmake || true

    if which pyenv > /dev/null; then
        eval "$(pyenv init -)"
    fi

    pyenv install 3.7.1
    pyenv virtualenv 3.7.1 conan
    pyenv rehash
    pyenv activate conan
fi

brew uninstall --force xquartz
brew remove xquartz || true
brew cask uninstall xquartz || true
brew cask zap xquartz || true

pushd conan/
pip install .
popd
pip install conan_package_tools bincrafters_package_tools
conan user
