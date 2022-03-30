from conftest import ac


def test_modelNames(setup):
    result = ac.modelNames()
    assert "test_model" in result


def test_modelNamesAndIds(setup):
    result = ac.modelNamesAndIds()
    assert isinstance(result["test_model"], int)


def test_modelFieldNames(setup):
    result = ac.modelFieldNames(modelName="test_model")
    assert result == ["field1", "field2"]


def test_modelFieldsOnTemplates(setup):
    result = ac.modelFieldsOnTemplates(modelName="test_model")
    assert result == {
        "Card 1": [["field1"], ["field2"]],
        "Card 2": [["field2"], ["field1"]],
    }


class TestCreateModel:
    createModel_kwargs = {
        "modelName": "test_model_foo",
        "inOrderFields": ["field1", "field2"],
        "cardTemplates": [{"Front": "{{field1}}", "Back": "{{field2}}"}],
    }

    def test_createModel_without_css(self, session_with_profile_loaded):
        ac.createModel(**self.createModel_kwargs)

    def test_createModel_with_css(self, session_with_profile_loaded):
        ac.createModel(**self.createModel_kwargs, css="* {}")


class TestStyling:
    def test_modelStyling(self, setup):
        result = ac.modelStyling(modelName="test_model")
        assert result == {"css": "* {}"}

    def test_updateModelStyling(self, setup):
        ac.updateModelStyling(model={
            "name": "test_model",
            "css": "* {color: red;}"
        })

        assert ac.modelStyling(modelName="test_model") == {
            "css": "* {color: red;}"
        }


class TestModelTemplates:
    def test_modelTemplates(self, setup):
        result = ac.modelTemplates(modelName="test_model")
        assert result == {
            "Card 1": {"Front": "{{field1}}", "Back": "{{field2}}"},
            "Card 2": {"Front": "{{field2}}", "Back": "{{field1}}"}
        }

    def test_updateModelTemplates(self, setup):
        ac.updateModelTemplates(model={
            "name": "test_model",
            "templates": {"Card 1": {"Front": "{{field1}}", "Back": "foo"}}
        })

        assert ac.modelTemplates(modelName="test_model") == {
            "Card 1": {"Front": "{{field1}}", "Back": "foo"},
            "Card 2": {"Front": "{{field2}}", "Back": "{{field1}}"}
        }


def test_findAndReplaceInModels(setup):
    ac.findAndReplaceInModels(
        modelName="test_model",
        findText="}}",
        replaceText="}}!",
        front=True,
        back=False,
        css=False,
    )

    ac.findAndReplaceInModels(
        modelName="test_model",
        findText="}}",
        replaceText="}}?",
        front=True,
        back=True,
        css=False,
    )

    ac.findAndReplaceInModels(
        modelName="test_model",
        findText="}",
        replaceText="color: blue;}",
        front=False,
        back=False,
        css=True,
    )

    assert ac.modelTemplates(modelName="test_model") == {
        "Card 1": {"Front": "{{field1}}?!", "Back": "{{field2}}?"},
        "Card 2": {"Front": "{{field2}}?!", "Back": "{{field1}}?"}
    }

    assert ac.modelStyling(modelName="test_model") == {
        "css": "* {color: blue;}"
    }
